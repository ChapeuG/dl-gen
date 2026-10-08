package br.com.datalake.utils

import com.amazonaws.services.sqs.AmazonSQSClientBuilder
import com.amazonaws.services.sqs.model.SendMessageRequest
import br.com.datalake.error.SparkErrorResult

import java.time.Instant

/**
 * Utilitario cross-projeto para envio de mensagens de erro a filas SQS.
 *
 * Converte um [[SparkErrorResult]] em um payload JSON estruturado e o entrega
 * a fila identificada pelo ARN fornecido.
 */
object SqsUtils {

  def sendError(
    sqsArn:  String,
    result:  SparkErrorResult,
    context: Map[String, String]
  ): Unit = {
    val region   = extractRegion(sqsArn)
    val queueUrl = arnToUrl(sqsArn)
    val payload  = buildPayload(result, context)

    val client = AmazonSQSClientBuilder.standard()
      .withRegion(region)
      .build()

    try {
      client.sendMessage(new SendMessageRequest(queueUrl, payload))
    } finally {
      client.shutdown()
    }
  }

  private def extractRegion(arn: String): String =
    arn.split(":")(3)

  private def arnToUrl(arn: String): String = {
    val parts     = arn.split(":")
    val region    = parts(3)
    val accountId = parts(4)
    val queueName = parts(5)
    s"https://sqs.$region.amazonaws.com/$accountId/$queueName"
  }

  private def buildPayload(result: SparkErrorResult, context: Map[String, String]): String = {
    val contextWithTimestamp = context + ("timestamp" -> Instant.now().toString)
    val contextJson = contextWithTimestamp
      .map { case (k, v) => s"""    "${escape(k)}": "${escape(v)}"""" }
      .mkString(",\n")

    s"""{
       |  "errorCategory":    "${escape(result.category.getClass.getSimpleName)}",
       |  "description":      "${escape(result.category.description)}",
       |  "retryable":        ${result.retryable},
       |  "programmingError": ${result.programmingError},
       |  "suggestedAction":  "${escape(result.suggestedAction)}",
       |  "errorMessage":     "${escape(Option(result.originalError.getMessage).getOrElse(""))}",
       |  "errorClass":       "${escape(result.originalError.getClass.getName)}",
       |  "context": {
       |$contextJson
       |  }
       |}""".stripMargin
  }

  private def escape(s: String): String =
    s.replace("\\", "\\\\")
     .replace("\"", "\\\"")
     .replace("\n", "\\n")
     .replace("\r", "\\r")
}
