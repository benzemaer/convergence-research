CREATE SCHEMA IF NOT EXISTS meta;
CREATE SCHEMA IF NOT EXISTS d0;
CREATE SCHEMA IF NOT EXISTS d1;
CREATE SCHEMA IF NOT EXISTS d2;
CREATE SCHEMA IF NOT EXISTS d3;

CREATE TABLE IF NOT EXISTS d1.security_master (
    data_version TEXT NOT NULL,
    universe_id TEXT NOT NULL,
    time_segment_id TEXT NOT NULL,
    security_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    exchange TEXT NOT NULL,
    security_name TEXT NOT NULL,
    listing_date DATE NOT NULL,
    delisting_date DATE,
    security_type TEXT NOT NULL,
    source_registry_id TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY (data_version, universe_id, time_segment_id, security_id)
);

CREATE TABLE IF NOT EXISTS d1.trading_calendar (
    data_version TEXT NOT NULL,
    universe_id TEXT NOT NULL,
    time_segment_id TEXT NOT NULL,
    exchange TEXT NOT NULL,
    trading_date DATE NOT NULL,
    is_trading_day BOOLEAN NOT NULL,
    calendar_session_type TEXT NOT NULL,
    source_registry_id TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY (data_version, universe_id, time_segment_id, exchange, trading_date)
);

CREATE TABLE IF NOT EXISTS d1.raw_market_prices (
    data_version TEXT NOT NULL,
    universe_id TEXT NOT NULL,
    time_segment_id TEXT NOT NULL,
    security_id TEXT NOT NULL,
    trading_date DATE NOT NULL,
    raw_open DOUBLE NOT NULL,
    raw_high DOUBLE NOT NULL,
    raw_low DOUBLE NOT NULL,
    raw_close DOUBLE NOT NULL,
    volume BIGINT NOT NULL,
    amount DOUBLE NOT NULL,
    trading_status TEXT NOT NULL,
    price_limit_status TEXT NOT NULL,
    source_registry_id TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    observed_at TIMESTAMP NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY (
        data_version,
        universe_id,
        security_id,
        trading_date,
        source_snapshot_id
    )
);

CREATE TABLE IF NOT EXISTS d1.corporate_actions (
    data_version TEXT NOT NULL,
    universe_id TEXT NOT NULL,
    time_segment_id TEXT NOT NULL,
    security_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    ex_date DATE NOT NULL,
    record_date DATE,
    pay_date DATE,
    action_terms TEXT NOT NULL,
    source_registry_id TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    observed_at TIMESTAMP NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY (
        data_version,
        universe_id,
        security_id,
        action_id,
        source_snapshot_id
    )
);

CREATE TABLE IF NOT EXISTS d1.trading_constraints (
    data_version TEXT NOT NULL,
    universe_id TEXT NOT NULL,
    time_segment_id TEXT NOT NULL,
    security_id TEXT NOT NULL,
    trading_date DATE NOT NULL,
    is_suspended BOOLEAN NOT NULL,
    is_st BOOLEAN NOT NULL,
    limit_up_price DOUBLE,
    limit_down_price DOUBLE,
    price_limit_status TEXT NOT NULL,
    tradable_flag BOOLEAN NOT NULL,
    source_registry_id TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    observed_at TIMESTAMP NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY (
        data_version,
        universe_id,
        security_id,
        trading_date,
        source_snapshot_id
    )
);

CREATE TABLE IF NOT EXISTS d2.adjusted_market_prices (
    data_version TEXT NOT NULL,
    universe_id TEXT NOT NULL,
    time_segment_id TEXT NOT NULL,
    security_id TEXT NOT NULL,
    trading_date DATE NOT NULL,
    adj_open DOUBLE NOT NULL,
    adj_high DOUBLE NOT NULL,
    adj_low DOUBLE NOT NULL,
    adj_close DOUBLE NOT NULL,
    adjustment_factor DOUBLE NOT NULL,
    adjustment_method TEXT NOT NULL,
    factor_as_of_time TIMESTAMP NOT NULL,
    corporate_action_flag BOOLEAN NOT NULL,
    adjustment_revision TEXT NOT NULL,
    source_registry_id TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY (
        data_version,
        universe_id,
        security_id,
        trading_date,
        adjustment_revision
    )
);

CREATE TABLE IF NOT EXISTS d2.market_price_quality_flags (
    data_version TEXT NOT NULL,
    universe_id TEXT NOT NULL,
    time_segment_id TEXT NOT NULL,
    security_id TEXT NOT NULL,
    trading_date DATE NOT NULL,
    quality_flag_id TEXT NOT NULL,
    quality_flag_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    rule_result TEXT NOT NULL,
    source_registry_id TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY (
        data_version,
        universe_id,
        security_id,
        trading_date,
        quality_flag_id
    )
);

CREATE TABLE IF NOT EXISTS d2.membership_alignment (
    data_version TEXT NOT NULL,
    universe_id TEXT NOT NULL,
    time_segment_id TEXT NOT NULL,
    security_id TEXT NOT NULL,
    index_code TEXT NOT NULL,
    membership_effective_date DATE NOT NULL,
    membership_mode TEXT NOT NULL,
    membership_source TEXT NOT NULL,
    source_registry_id TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY (
        data_version,
        universe_id,
        security_id,
        index_code,
        membership_effective_date
    )
);

CREATE TABLE IF NOT EXISTS d3.daily_market_observations (
    data_version TEXT NOT NULL,
    universe_id TEXT NOT NULL,
    time_segment_id TEXT NOT NULL,
    security_id TEXT NOT NULL,
    trading_date DATE NOT NULL,
    observation_revision TEXT NOT NULL,
    observed_at TIMESTAMP NOT NULL,
    raw_price_ref TEXT NOT NULL,
    adjusted_price_ref TEXT NOT NULL,
    trading_constraint_ref TEXT NOT NULL,
    membership_ref TEXT NOT NULL,
    calendar_ref TEXT NOT NULL,
    price_fact_source TEXT NOT NULL,
    corporate_action_source TEXT NOT NULL,
    membership_source TEXT NOT NULL,
    calendar_source TEXT NOT NULL,
    revision_policy TEXT NOT NULL,
    observed_at_rule TEXT NOT NULL,
    source_registry_id TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY (
        data_version,
        universe_id,
        security_id,
        trading_date,
        observation_revision
    )
);
