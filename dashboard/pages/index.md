---
title: Sirens Network Analytics
---

Total audience reach and growth dynamics across all Sirens alert channels.
Snapshots are recorded throughout the day.

```sql headline
-- Comparisons are looked up by date rather than with lag(n): a missed snapshot
-- leaves a gap in the history, and counting rows back would measure against
-- the wrong day.
with per_snapshot as (
    select
        date,
        date::date as day_date,
        sum(subscribers) as total
    from sirens.subscribers
    group by 1, 2
),
latest_per_day as (
    select
        day_date as date,
        total
    from (
        select
            day_date,
            total,
            row_number() over (partition by day_date order by date desc) as rn
        from per_snapshot
    )
    where rn = 1
)
select
    day.total,
    day.total - prev_day.total  as change_1d,
    day.total - prev_week.total as change_7d
from latest_per_day day
left join latest_per_day prev_day  on prev_day.date  = day.date - 1
left join latest_per_day prev_week on prev_week.date = day.date - 7
order by day.date desc
limit 1
```

<BigValue
    data={headline}
    value=total
    title="Total Network Audience"
    comparison=change_1d
    comparisonTitle="since yesterday"
/>

<BigValue
    data={headline}
    value=change_7d
    title="7-Day Net Growth"
/>

## Network Growth

Aggregate subscriber trajectory across all monitored alert channels over time.

<ButtonGroup name=timeframe defaultValue="7d">
    <ButtonGroupItem valueLabel="24H" value="24h" />
    <ButtonGroupItem valueLabel="7D" value="7d" />
    <ButtonGroupItem valueLabel="30D" value="30d" />
</ButtonGroup>

```sql daily_total
with per_snapshot as (
    select
        date,
        date::date as day_date,
        sum(subscribers) as total
    from sirens.subscribers
    group by 1, 2
),
latest_per_day as (
    select
        day_date as date,
        total
    from (
        select
            day_date,
            total,
            row_number() over (partition by day_date order by date desc) as rn
        from per_snapshot
    )
    where rn = 1
),
view_24h as (
    select
        date,
        total
    from per_snapshot
    where date >= (select max(date) from per_snapshot) - interval '24 hours'
),
view_7d as (
    select
        date::timestamp as date,
        total
    from latest_per_day
    where date >= (select max(date) from latest_per_day) - interval '7 days'
),
view_30d as (
    select
        date::timestamp as date,
        total
    from latest_per_day
    where date >= (select max(date) from latest_per_day) - interval '30 days'
)
select
    date,
    total
from (
    select * from view_24h
    where '${inputs.timeframe.value}' = '24h' or '${inputs.timeframe}' = '24h'
    union all
    select * from view_7d
    where ('${inputs.timeframe.value}' = '7d' or '${inputs.timeframe}' = '7d')
       or ('${inputs.timeframe.value}' is null and '${inputs.timeframe}' is null)
       or ('${inputs.timeframe.value}' not in ('24h', '30d') and '${inputs.timeframe}' not in ('24h', '30d'))
    union all
    select * from view_30d
    where '${inputs.timeframe.value}' = '30d' or '${inputs.timeframe}' = '30d'
)
order by 1
```

<LineChart
    data={daily_total}
    x=date
    y=total
    yAxisTitle="subscribers"
    yScale=true
    markers=true
    chartAreaHeight=280
    echartsOptions={{useUTC: true}}
/>

## Daily Channel Movement

```sql movement_window
with current_run as (
    select max(date) as current_time
    from sirens.subscribers
),
previous_day_run as (
    select coalesce(
        (select max(date) from sirens.subscribers where date::date < (select current_time::date from current_run)),
        (select min(date) from sirens.subscribers)
    ) as prev_time
    from current_run
)
select
    strftime(previous_day_run.prev_time, '%B %-d, %Y %H:%M') as earlier,
    strftime(current_run.current_time, '%B %-d, %Y %H:%M') as later
from current_run, previous_day_run
```

Net subscriber change per channel between {movement_window[0].earlier} and {movement_window[0].later}.

```sql movement
with current_run as (
    select max(date) as current_time
    from sirens.subscribers
),
previous_day_run as (
    select coalesce(
        (select max(date) from sirens.subscribers where date::date < (select current_time::date from current_run)),
        (select min(date) from sirens.subscribers)
    ) as prev_time
    from current_run
),
later_counts as (
    select display_name, subscribers
    from sirens.subscribers, current_run
    where date = current_run.current_time
),
earlier_counts as (
    select display_name, subscribers
    from sirens.subscribers, previous_day_run
    where date = previous_day_run.prev_time
)
select
    later.display_name,
    later.subscribers - coalesce(earlier.subscribers, later.subscribers) as change,
    case
        when later.subscribers > coalesce(earlier.subscribers, later.subscribers) then 'Gained'
        when later.subscribers < coalesce(earlier.subscribers, later.subscribers) then 'Lost'
        else 'Unchanged'
    end as direction
from later_counts later
left join earlier_counts earlier
       on earlier.display_name = later.display_name
order by change desc, later.display_name
```

<BarChart
    data={movement}
    x=display_name
    y=change
    series=direction
    seriesColors={{Gained: '#2f9e44', Lost: '#e03131', Unchanged: '#adb5bd'}}
    swapXY=true
    sort=false
    yAxisTitle="change in subscribers"
    echartsOptions={{xAxis: {minInterval: 1}}}
/>

## Subscribers by Channel

Audience distribution by channel, ranked by total subscriber count.

```sql by_channel
select
    display_name,
    subscribers
from sirens.subscribers
where date = (select max(date) from sirens.subscribers)
order by subscribers desc
```

<BarChart
    data={by_channel}
    x=display_name
    y=subscribers
    swapXY=true
    yAxisTitle="subscribers"
/>

Data as of {movement_window[0].later}. Historical tracking begins from the date
metrics collection was enabled. To ensure data integrity, incomplete snapshots
are omitted rather than recorded partially — any gaps in the trend line indicate
a missed run, not lost subscribers.