CREATE TABLE public.cred_final (
    cd_credenciadora    INTEGER NOT NULL,
    nm_credenciadora    VARCHAR(255) NOT NULL,
    nm_produto          VARCHAR(100) NOT NULL,
    nm_variante         VARCHAR(100) NOT NULL,
    tipo_pessoa         VARCHAR(10) NOT NULL,
    visao               VARCHAR(50) NOT NULL,
    data                DATE NOT NULL,
    predito_final       DOUBLE PRECISION,
    predito_final_10    DOUBLE PRECISION
);
