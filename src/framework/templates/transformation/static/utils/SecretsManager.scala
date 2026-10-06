package br.com.datalake.utils

import com.amazonaws.services.secretsmanager.AWSSecretsManagerClientBuilder
import com.amazonaws.services.secretsmanager.model.GetSecretValueRequest

/**
 * Utilitario cross-projeto para recuperacao de segredos no AWS Secrets Manager.
 *
 * Recebe o ARN de um segredo e retorna a secret string associada.
 * A regiao e extraida diretamente do ARN.
 */
object SecretsManager {

  def getSecretString(secretArn: String): String = {
    val region = extractRegion(secretArn)
    val client = AWSSecretsManagerClientBuilder.standard()
      .withRegion(region)
      .build()

    try {
      val request = new GetSecretValueRequest().withSecretId(secretArn)
      client.getSecretValue(request).getSecretString
    } finally {
      client.shutdown()
    }
  }

  private def extractRegion(arn: String): String =
    arn.split(":")(3)
}
