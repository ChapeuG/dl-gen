package br.com.datalake.utils

/**
 * Construcao e derivacao de paths S3 no padrao `s3://<bucket>/<team>/<dataset>/<table>`.
 */
object FileUtils {

  /**
   * Deriva o base path (`s3://<bucket>`) a partir do path de uma tabela,
   * removendo os tres ultimos segmentos (`team/dataset/table`).
   */
  def deriveBasePathFromTableUri(tableUri: String): String = {
    val normalized = tableUri.stripSuffix("/")
    val schemeEnd  = normalized.indexOf("://") + 3
    val segments   = normalized.substring(schemeEnd).split("/")
    if (segments.length < 4)
      throw new IllegalArgumentException(s"output_uri fora do padrao s3://<bucket>/<team>/<dataset>/<table>: $tableUri")
    normalized.substring(0, schemeEnd) + segments.dropRight(3).mkString("/")
  }

  /** Path da tabela Delta de lookup: `<basePath>/<team>/<dataset>/<table>`. */
  def getS3PathToDeltaTable(basePath: String, team: String, dataset: String, table: String): String =
    s"${basePath.stripSuffix("/")}/$team/$dataset/$table"
}
