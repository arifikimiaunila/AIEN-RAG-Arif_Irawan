ROLE_COLUMNS = {
    "ops_logistik": ["carrier_id", "shipment_count", "delivered_count", "late_delivered_count", "on_time_delivered_count", "in_transit_count", "refund_amount_idr"],
    "finance_anti_fraud": ["shipping_fee_idr", "refund_amount_idr"],
    "marketing": ["city_daily"],
    "executive": ["*"],
    "customer_service": ["delivered_count", "late_delivered_count"],
    "ops_logistik_kurir": ["carrier_id", "shipment_count", "delivered_count", "late_delivered_count", "on_time_delivered_count", "in_transit_count", "refund_amount_idr", "shipping_fee_idr"],
}