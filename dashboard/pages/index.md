---
title: Sirens Network Subscribers
---

```sql daily_total
select
    date,
    sum(participants) as total
from sirens.channel_stats
group by date
order by date
```

```sql headline
select
    total,
    total - lag(total)     over (order by date) as change_1d,
    total - lag(total, 7)  over (order by date) as change_7d
from (
    select date, sum(participants) as total
    from sirens.channel_stats
    group by date
)
order by date desc
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
select max(date) as day from sirens.channel_stats
```

Data as of <Value data={latest_day} column=day/>. Channels are counted once a
day; the history starts on the day counting was switched on.
