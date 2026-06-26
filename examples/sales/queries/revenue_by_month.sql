SELECT
    date_trunc('month', order_date) AS order_month,
    COUNT(*) AS order_count,
    SUM(total_amount) AS revenue
FROM orders
GROUP BY 1
ORDER BY 1;
