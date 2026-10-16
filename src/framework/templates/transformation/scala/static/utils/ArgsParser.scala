package br.com.datalake.utils

/**
 * Utilitario cross-projeto para parsing de argumentos de linha de comando.
 *
 * Interpreta argumentos no formato `--chave valor`, sem exigir ordem fixa.
 */
object ArgsParser {

  /**
   * Converte um array de argumentos no formato `--chave valor` em um mapa.
   *
   * @param args Array de argumentos recebido pelo `main`.
   * @return Mapa de `chave -> valor` sem o prefixo `--`.
   */
  def parse(args: Array[String]): Map[String, String] =
    args.sliding(2, 2).collect {
      case Array(key, value) if key.startsWith("--") => key.stripPrefix("--") -> value
    }.toMap
}
