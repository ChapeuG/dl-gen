CREATE TABLE public.forecast_produto (
    cd_emissor       VARCHAR(20) NOT NULL,
    nm_emissor       VARCHAR(255) NOT NULL,
    nm_produto       VARCHAR(100) NOT NULL,
    nm_variante      VARCHAR(100) NOT NULL,
    data             DATE NOT NULL,
    predito          DOUBLE PRECISION,
    predito_crd_p    DOUBLE PRECISION,
    predito_crd_v    DOUBLE PRECISION
);
