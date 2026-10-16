package br.com.datalake.error

import org.apache.spark.SparkException
import org.apache.spark.sql.AnalysisException
import org.apache.spark.sql.catalyst.analysis.NoSuchTableException
import org.apache.spark.sql.streaming.StreamingQueryException

import java.io.IOException
import java.net.{ConnectException, SocketTimeoutException, UnknownHostException}
import java.sql.SQLException
import scala.util.{Failure, Success, Try}

// =============================================================================
// ADT — Categorias de erro
// =============================================================================

sealed trait ErrorCategory {
  def retryable: Boolean
  def programmingError: Boolean
  def description: String
  def cause: Throwable
}

object ErrorCategory {

  final case class ConnectivityError(cause: Throwable, detail: String = "") extends ErrorCategory {
    val retryable       = true
    val programmingError = false
    val description     = s"Connectivity/network failure — retryable. Detail: ${if (detail.nonEmpty) detail else cause.getMessage}"
  }

  final case class ResourceExhaustionError(cause: Throwable, detail: String = "") extends ErrorCategory {
    val retryable       = true
    val programmingError = false
    val description     = s"Resource exhaustion (OOM / disk / shuffle) — retryable with resource adjustment. Detail: ${if (detail.nonEmpty) detail else cause.getMessage}"
  }

  final case class DataSchemaError(cause: Throwable, detail: String = "") extends ErrorCategory {
    val retryable       = false
    val programmingError = true
    val description     = s"Data/schema error — programming fix required. Detail: ${if (detail.nonEmpty) detail else cause.getMessage}"
  }

  final case class AuthorizationError(cause: Throwable, detail: String = "") extends ErrorCategory {
    val retryable       = false
    val programmingError = false
    val description     = s"Authorization/authentication failure — credentials or ACL fix required. Detail: ${if (detail.nonEmpty) detail else cause.getMessage}"
  }

  final case class BroadcastTimeoutError(cause: Throwable, detail: String = "") extends ErrorCategory {
    val retryable       = true
    val programmingError = false
    val description     = s"Broadcast join timeout — consider increasing spark.sql.broadcastTimeout or disabling broadcast. Detail: ${if (detail.nonEmpty) detail else cause.getMessage}"
  }

  final case class ConfigurationError(cause: Throwable, detail: String = "") extends ErrorCategory {
    val retryable       = false
    val programmingError = true
    val description     = s"Job configuration error — fix configuration before retrying. Detail: ${if (detail.nonEmpty) detail else cause.getMessage}"
  }

  final case class UnknownError(cause: Throwable, detail: String = "") extends ErrorCategory {
    val retryable       = false
    val programmingError = false
    val description     = s"Unknown/unclassified error — manual investigation required. Detail: ${if (detail.nonEmpty) detail else cause.getMessage}"
  }
}

// =============================================================================
// Resultado padronizado do handler
// =============================================================================

final case class SparkErrorResult(
  category:         ErrorCategory,
  originalError:    Throwable,
  retryable:        Boolean,
  programmingError: Boolean,
  suggestedAction:  String
)

// =============================================================================
// Classificador principal
// =============================================================================

object SparkErrorHandler {

  import ErrorCategory._

  def classify(error: Throwable): SparkErrorResult = {
    val category = classifyInternal(error)
    SparkErrorResult(
      category         = category,
      originalError    = error,
      retryable        = category.retryable,
      programmingError = category.programmingError,
      suggestedAction  = buildSuggestedAction(category)
    )
  }

  def run[A](block: => A): Either[SparkErrorResult, A] =
    Try(block) match {
      case Success(value) => Right(value)
      case Failure(ex)    => Left(classify(ex))
    }

  private def classifyInternal(error: Throwable): ErrorCategory = {
    val chain = causalChain(error)

    chain.collectFirst {

      case e: SparkException if isBroadcastTimeout(e) =>
        BroadcastTimeoutError(e, "spark.sql.broadcastTimeout exceeded")

      case e: SparkException if isShuffleFetchFailure(e) =>
        ResourceExhaustionError(e, "Shuffle FetchFailedException — possible executor loss or disk pressure")

      case e: OutOfMemoryError =>
        ResourceExhaustionError(e, "JVM OutOfMemoryError")

      case e: SparkException if containsMessage(e, "GC overhead limit exceeded") =>
        ResourceExhaustionError(e, "GC overhead limit — increase executor memory")

      case e: IOException if containsMessage(e, "No space left on device") =>
        ResourceExhaustionError(e, "Disk full on executor/driver node")

      case e if isAuthError(e) =>
        AuthorizationError(e, "ACL or Kerberos authentication failure")

      case e: SecurityException =>
        AuthorizationError(e, "SecurityException — check IAM roles or file permissions")

      case e: AnalysisException =>
        DataSchemaError(e, s"Spark AnalysisException: ${e.getMessage}")

      case e: NoSuchTableException =>
        DataSchemaError(e, s"Table not found: ${e.getMessage}")

//      case e: org.apache.spark.sql.catalyst.errors.package.TreeNodeException[_] =>
//        DataSchemaError(e, "Catalyst TreeNode error — likely malformed query or schema mismatch")

//      case e: org.apache.spark.SparkUpgradeException =>
//        DataSchemaError(e, "SparkUpgradeException — data/behavior change between Spark versions")

      case e: ConnectException =>
        ConnectivityError(e, s"TCP connection refused: ${e.getMessage}")

      case e: UnknownHostException =>
        ConnectivityError(e, s"DNS resolution failure: ${e.getMessage}")

      case e: SocketTimeoutException =>
        ConnectivityError(e, s"Socket timeout: ${e.getMessage}")

      case e: IOException if isConnectivityIOException(e) =>
        ConnectivityError(e, e.getMessage)

      case e: SQLException if isSqlConnectivity(e) =>
        ConnectivityError(e, s"JDBC connectivity error (SQLState: ${e.getSQLState}): ${e.getMessage}")

      case e: StreamingQueryException =>
        classifyInternal(e.getCause)

      case e: ClassNotFoundException =>
        ConfigurationError(e, s"Class not found — check --jars or --packages: ${e.getMessage}")

      case e: NoClassDefFoundError =>
        ConfigurationError(e, s"NoClassDefFoundError — dependency missing: ${e.getMessage}")

      case e: IllegalArgumentException =>
        ConfigurationError(e, s"Illegal argument — check job parameters: ${e.getMessage}")

    }.getOrElse(UnknownError(error))
  }

  private def causalChain(t: Throwable, acc: List[Throwable] = Nil): List[Throwable] = {
    val chain = t :: acc
    Option(t.getCause) match {
      case Some(cause) if !chain.contains(cause) => causalChain(cause, chain)
      case _                                      => chain.reverse
    }
  }

  private def containsMessage(t: Throwable, fragment: String): Boolean =
    Option(t.getMessage).exists(_.toLowerCase.contains(fragment.toLowerCase))

  private def isBroadcastTimeout(e: SparkException): Boolean =
    containsMessage(e, "broadcast") && (
      containsMessage(e, "timeout") || containsMessage(e, "timed out")
    )

  private def isShuffleFetchFailure(e: SparkException): Boolean =
    containsMessage(e, "FetchFailed") ||
    containsMessage(e, "shuffle") && containsMessage(e, "failed")

  private def isAuthError(t: Throwable): Boolean = {
    val msg = Option(t.getMessage).getOrElse("").toLowerCase
    val cls = t.getClass.getName.toLowerCase
    msg.contains("kerberos") ||
    msg.contains("authentication failed") ||
    msg.contains("403") ||
    msg.contains("access denied") ||
    msg.contains("permission denied") ||
    cls.contains("accesscontrolexception") ||
    cls.contains("accessdenied")
  }

  private def isConnectivityIOException(e: IOException): Boolean = {
    val msg = Option(e.getMessage).getOrElse("").toLowerCase
    msg.contains("connection") ||
    msg.contains("network") ||
    msg.contains("unreachable") ||
    msg.contains("s3") ||
    msg.contains("hdfs") ||
    msg.contains("timeout")
  }

  private def isSqlConnectivity(e: SQLException): Boolean =
    Option(e.getSQLState).exists(_.startsWith("08"))

  private def buildSuggestedAction(category: ErrorCategory): String = category match {
    case _: ConnectivityError =>
      "Retry with exponential backoff. Verify network/DNS, check endpoint availability and firewall rules."
    case _: ResourceExhaustionError =>
      "Retry after increasing executor memory/cores or reducing partition size. Review broadcast join thresholds."
    case _: DataSchemaError =>
      "Do NOT retry automatically. Fix schema definition, column names, or data casting logic in the code."
    case _: AuthorizationError =>
      "Do NOT retry automatically. Renew Kerberos ticket or fix IAM/ACL permissions, then redeploy."
    case _: BroadcastTimeoutError =>
      "Retry after increasing spark.sql.broadcastTimeout or disabling broadcast with spark.sql.autoBroadcastJoinThreshold=-1."
    case _: ConfigurationError =>
      "Do NOT retry automatically. Fix job configuration, dependencies, or invalid parameters."
    case _: UnknownError =>
      "Manual investigation required. Check driver/executor logs for full stack trace."
  }
}
