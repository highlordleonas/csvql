WITH monthly_changes AS (
    SELECT
        CAST(movement_month AS DATE) AS report_month,
        SUM(CASE WHEN movement_type = 'new' THEN mrr_delta ELSE 0 END) AS new_mrr,
        SUM(CASE WHEN movement_type = 'expansion' THEN mrr_delta ELSE 0 END) AS expansion_mrr,
        SUM(CASE WHEN movement_type = 'contraction' THEN ABS(mrr_delta) ELSE 0 END) AS contraction_mrr,
        SUM(CASE WHEN movement_type = 'churn' THEN ABS(mrr_delta) ELSE 0 END) AS churn_mrr,
        SUM(CASE WHEN movement_type = 'reactivation' THEN mrr_delta ELSE 0 END) AS reactivation_mrr,
        SUM(mrr_delta) AS net_mrr_change
    FROM revenue_movements
    GROUP BY 1
),
monthly_balances AS (
    SELECT
        report_month,
        new_mrr,
        expansion_mrr,
        contraction_mrr,
        churn_mrr,
        reactivation_mrr,
        net_mrr_change,
        SUM(net_mrr_change) OVER (ORDER BY report_month) AS ending_mrr
    FROM monthly_changes
),
revenue_health AS (
    SELECT
        CAST(report_month AS VARCHAR) AS report_month,
        COALESCE(LAG(ending_mrr) OVER (ORDER BY report_month), 0) AS starting_mrr,
        new_mrr,
        expansion_mrr,
        contraction_mrr,
        churn_mrr,
        reactivation_mrr,
        net_mrr_change,
        ending_mrr
    FROM monthly_balances
)
SELECT
    report_month,
    ROUND(starting_mrr, 1) AS starting_mrr,
    ROUND(new_mrr, 1) AS new_mrr,
    ROUND(expansion_mrr, 1) AS expansion_mrr,
    ROUND(contraction_mrr, 1) AS contraction_mrr,
    ROUND(churn_mrr, 1) AS churn_mrr,
    ROUND(reactivation_mrr, 1) AS reactivation_mrr,
    ROUND(net_mrr_change, 1) AS net_mrr_change,
    ROUND(ending_mrr, 1) AS ending_mrr,
    ROUND(ending_mrr * 12, 1) AS ending_arr,
    CASE
        WHEN starting_mrr = 0 THEN NULL
        ELSE ROUND(
            (
                starting_mrr
                + expansion_mrr
                + reactivation_mrr
                - contraction_mrr
                - churn_mrr
            ) / starting_mrr * 100,
            1
        )
    END AS net_revenue_retention_pct
FROM revenue_health
ORDER BY report_month;
