CREATE SCHEMA IF NOT EXISTS gold;

DROP VIEW IF EXISTS gold.carrier_summary CASCADE;
DROP TABLE IF EXISTS gold.shipment_fact CASCADE;
DROP TABLE IF EXISTS gold.city_daily CASCADE;
DROP TABLE IF EXISTS gold.carrier_daily CASCADE;

CREATE TABLE gold.carrier_daily (
    metric_date             DATE NOT NULL,
    carrier_id              VARCHAR(100) NOT NULL,
    shipment_count          INTEGER DEFAULT 0,
    delivered_count         INTEGER DEFAULT 0,
    on_time_delivered_count INTEGER DEFAULT 0,
    late_delivered_count    INTEGER DEFAULT 0,
    in_transit_count        INTEGER DEFAULT 0,
    shipping_fee_idr        NUMERIC(18, 2) DEFAULT 0.00,
    refund_amount_idr       NUMERIC(18, 2) DEFAULT 0.00,
    CONSTRAINT pk_carrier_daily PRIMARY KEY (metric_date, carrier_id)
);

CREATE TABLE gold.city_daily (
    metric_date             DATE NOT NULL,
    destination_city        VARCHAR(150) NOT NULL,
    shipment_count          INTEGER DEFAULT 0,
    delivered_count         INTEGER DEFAULT 0,
    on_time_delivered_count INTEGER DEFAULT 0,
    late_delivered_count    INTEGER DEFAULT 0,
    in_transit_count        INTEGER DEFAULT 0,
    shipping_fee_idr        NUMERIC(18, 2) DEFAULT 0.00,
    refund_amount_idr       NUMERIC(18, 2) DEFAULT 0.00,
    CONSTRAINT pk_city_daily PRIMARY KEY (metric_date, destination_city)
);

CREATE TABLE gold.shipment_fact (
    shipment_id              TEXT PRIMARY KEY,
    order_date               DATE NOT NULL,
    carrier_id               TEXT NOT NULL CHECK (carrier_id IN ('C01', 'C02', 'C03')),
    origin_hub               TEXT NOT NULL,
    destination_city         TEXT NOT NULL,
    service_level            TEXT NOT NULL CHECK (service_level IN ('standard', 'express')),
    promised_delivery_at_utc TIMESTAMPTZ NOT NULL,
    delivered_at_utc         TIMESTAMPTZ NULL,
    delivery_status          TEXT NOT NULL CHECK (delivery_status IN ('delivered', 'in_transit')),
    shipping_fee_idr         NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    refund_amount_idr        NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    exception_note           TEXT NULL
);

CREATE INDEX idx_shipment_fact_date_carrier ON gold.shipment_fact (order_date, carrier_id);
CREATE INDEX idx_shipment_fact_date_city ON gold.shipment_fact (order_date, destination_city);

CREATE OR REPLACE VIEW gold.carrier_summary AS
SELECT
    carrier_id,
    COUNT(*) AS shipment_count,
    SUM(CASE WHEN delivery_status = 'delivered' THEN 1 ELSE 0 END) AS delivered_count,
    SUM(CASE WHEN delivery_status = 'in_transit' THEN 1 ELSE 0 END) AS in_transit_count,
    SUM(CASE WHEN delivery_status = 'delivered' AND delivered_at_utc <= promised_delivery_at_utc THEN 1 ELSE 0 END) AS on_time_delivered_count,
    SUM(CASE WHEN delivery_status = 'delivered' AND delivered_at_utc > promised_delivery_at_utc THEN 1 ELSE 0 END) AS late_delivered_count,
    SUM(shipping_fee_idr) AS total_shipping_fee_idr,
    SUM(refund_amount_idr) AS total_refund_amount_idr,
    ROUND(
        100.0 * SUM(CASE WHEN delivery_status = 'delivered' AND delivered_at_utc <= promised_delivery_at_utc THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN delivery_status = 'delivered' THEN 1 ELSE 0 END), 0),
        2
    ) AS on_time_delivery_rate_pct
FROM gold.shipment_fact
GROUP BY carrier_id;