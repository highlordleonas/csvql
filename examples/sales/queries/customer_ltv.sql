SELECT
    c.customer_id,
    c.email,
    COUNT(o.order_id) AS order_count,
    SUM(o.total_amount) AS lifetime_value
FROM customers c
JOIN orders o USING (customer_id)
GROUP BY c.customer_id, c.email
ORDER BY lifetime_value DESC;
