-- Demo warehouse for the NL2SQL flow.
--
-- Deliberately a separate database with its own read-only role. The generated-SQL
-- path connects as `mnemos_ro`, which has USAGE + SELECT and nothing else, so the
-- AST read-only guard in the application is a second line of defence rather than
-- the only one. Defence in depth: even a perfect prompt injection that defeats the
-- parser cannot write, because the role cannot write.

\connect mnemos_analytics

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE analytics.region (
    region_id    serial PRIMARY KEY,
    region_name  text NOT NULL UNIQUE,
    country      text NOT NULL
);

CREATE TABLE analytics.product (
    product_id   serial PRIMARY KEY,
    product_name text NOT NULL,
    category     text NOT NULL,
    unit_price   numeric(12,2) NOT NULL
);

CREATE TABLE analytics.customer (
    customer_id  serial PRIMARY KEY,
    customer_name text NOT NULL,
    region_id    integer NOT NULL REFERENCES analytics.region(region_id),
    signed_up_on date NOT NULL,
    segment      text NOT NULL
);

CREATE TABLE analytics.sales_order (
    order_id     serial PRIMARY KEY,
    customer_id  integer NOT NULL REFERENCES analytics.customer(customer_id),
    product_id   integer NOT NULL REFERENCES analytics.product(product_id),
    ordered_on   date NOT NULL,
    quantity     integer NOT NULL CHECK (quantity > 0),
    net_amount   numeric(14,2) NOT NULL,
    status       text NOT NULL
);

CREATE INDEX ON analytics.sales_order (ordered_on);
CREATE INDEX ON analytics.sales_order (customer_id);
CREATE INDEX ON analytics.customer (region_id);

INSERT INTO analytics.region (region_name, country) VALUES
    ('EMEA West', 'Germany'), ('EMEA South', 'Portugal'),
    ('APAC North', 'India'),  ('AMER East', 'United States');

INSERT INTO analytics.product (product_name, category, unit_price) VALUES
    ('Atlas Servo Arm',      'robotics',   4250.00),
    ('Atlas Gripper v3',     'robotics',    980.00),
    ('Vision Module VX2',    'perception', 2150.00),
    ('LiDAR Scanner L9',     'perception', 6400.00),
    ('Fleet Controller',     'software',   1200.00),
    ('Maintenance Plan Pro', 'services',    750.00);

INSERT INTO analytics.customer (customer_name, region_id, signed_up_on, segment) VALUES
    ('Rheinmetall Logistics', 1, '2024-02-11', 'enterprise'),
    ('Porto Automacao',       2, '2024-06-03', 'mid-market'),
    ('Bengaluru Robotics Co', 3, '2025-01-20', 'enterprise'),
    ('Hudson Fulfilment',     4, '2024-09-14', 'enterprise'),
    ('Lisboa Micromanufact',  2, '2025-03-02', 'smb'),
    ('Pune Assembly Works',   3, '2025-07-19', 'mid-market');

-- Deterministic pseudo-random order history so the demo is reproducible.
INSERT INTO analytics.sales_order (customer_id, product_id, ordered_on, quantity, net_amount, status)
SELECT
    1 + (n * 7) % 6,
    1 + (n * 5) % 6,
    DATE '2025-01-01' + ((n * 11) % 540),
    1 + (n % 9),
    ROUND((((n * 37) % 900) + 120)::numeric * (1 + (n % 9)), 2),
    (ARRAY['completed','completed','completed','pending','cancelled'])[1 + (n % 5)]
FROM generate_series(1, 900) AS n;

-- Read-only role used by the NL2SQL flow.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mnemos_ro') THEN
        CREATE ROLE mnemos_ro LOGIN PASSWORD 'mnemos_ro_dev';
    END IF;
END $$;

GRANT CONNECT ON DATABASE mnemos_analytics TO mnemos_ro;
GRANT USAGE  ON SCHEMA analytics TO mnemos_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO mnemos_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO mnemos_ro;

-- Explicitly withhold everything else. Being loud about this in the seed script
-- means the guarantee is visible to anyone reading the repo.
REVOKE CREATE ON SCHEMA analytics FROM mnemos_ro;
REVOKE ALL ON SCHEMA public FROM mnemos_ro;
