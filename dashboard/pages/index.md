---
title: Sirens Network Subscribers
---

```sql daily_total
select
    date::date as date,
    sum(participants) as total
from sirens.channel_stats
group by 1
order by 1
```

```sql headline
-- Comparisons are looked up by date rather than with lag(n): a night the
-- snapshot failed leaves a gap in the history, and counting rows back would
-- then quietly measure against the wrong day.
with per_day as (
    select date::date as date, sum(participants) as total
    from sirens.channel_stats
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
    title="Subscribers across the network"
    comparison=change_1d
    comparisonTitle="past day"
/>

<BigValue
    data={headline}
    value=change_7d
    title="Past week"
/>

## Trend

<LineChart
    data={daily_total}
    x=date
    y=total
    yAxisTitle="subscribers"
    yMin=0
/>

## Channels

```sql by_channel
select
    display_name,
    participants
from sirens.channel_stats
where date = (select max(date) from sirens.channel_stats)
order by participants desc
```

<DataTable data={by_channel} rows=40 search=true>
    <Column id=display_name title="City"/>
    <Column id=participants title="Subscribers" fmt=num0/>
</DataTable>

```sql latest_day
select max(date::date) as day from sirens.channel_stats
```

Data as of <Value data={latest_day} column=day/>. Channels are counted once a
day; the history starts on the day counting was switched on. A day the snapshot
could not reach most of the network is left out entirely rather than stored
short, so a gap in the line means a failed run, never lost subscribers.
