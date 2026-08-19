---
title: Sirens Network Analytics
---

Total audience reach and growth dynamics across all Sirens alert channels.
Snapshots are recorded daily shortly after midnight (EEST).

```sql headline
-- Comparisons are looked up by date rather than with lag(n): a night the
-- snapshot failed leaves a gap in the history, and counting rows back would
-- then quietly measure against the wrong day.
with per_day as (
    select date::date as date, sum(subscribers) as total
    from sirens.subscribers
    group by 1
)
select
    day.total,
    day.total - prev_day.total  as change_1d,
    day.total - prev_week.total as change_7d
from per_day day
left join per_day prev_day  on prev_day.date  = day.date - 1
left join per_day prev_week on prev_week.date = day.date - 7
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
select
    date::date as date,
    sum(subscribers) as total
from sirens.subscribers
where
    date::date >= (select max(date::date) from sirens.subscribers) -
    case
        when '${inputs.timeframe.value}' = '24h' or '${inputs.timeframe}' = '24h'
            then interval '1 day'
        when '${inputs.timeframe.value}' = '30d' or '${inputs.timeframe}' = '30d'
            then interval '30 days'
        else
            interval '7 days'
    end
group by 1
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
/>

## Daily Channel Movement

```sql movement_window
with recent as (
    select distinct date::date as date
    from sirens.subscribers
    order by 1 desc
    limit 2
)
select
    strftime(min(date), '%B %-d, %Y') as earlier,
    strftime(max(date), '%B %-d, %Y') as later
from recent
```

Net subscriber change per channel between {movement_window[0].earlier} and {movement_window[0].later}.

```sql movement
with counts as (
    select display_name, date::date as date, subscribers
    from sirens.subscribers
),
recent as (
    select distinct date from counts order by date desc limit 2
)
select
    later.display_name,
    later.subscribers - earlier.subscribers as change,
    case
        when later.subscribers > earlier.subscribers then 'Gained'
        when later.subscribers < earlier.subscribers then 'Lost'
        else 'Unchanged'
    end as direction
from counts later
join counts earlier
      on earlier.display_name = later.display_name
     and earlier.date = (select min(date) from recent)
where later.date = (select max(date) from recent)
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
where date::date = (select max(date::date) from sirens.subscribers)
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