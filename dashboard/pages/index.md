---
title: Sirens Internal Statistics
---

How many people the Sirens alert channels reach. Every channel is counted once
a day, shortly after midnight EEST time.

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
    title="Subscribers across the network"
    comparison=change_1d
    comparisonTitle="since yesterday"
/>

<BigValue
    data={headline}
    value=change_7d
    title="Change over the past week"
/>

## Growth over time

Total subscriber network growth over time across all tracked alert channels.

<ButtonGroup name=timeframe defaultValue="7d">
    <ButtonGroupItem valueLabel="24H" value="24h" />
    <ButtonGroupItem valueLabel="7D" value="7d" />
    <ButtonGroupItem valueLabel="30D" value="30d" />
    <ButtonGroupItem valueLabel="90D" value="90d" />
    <ButtonGroupItem valueLabel="All" value="all" />
</ButtonGroup>

```sql daily_total
select
    date::date as date,
    sum(subscribers) as total
from sirens.subscribers
where
    case
        when '${inputs.timeframe.value}' in ('24h', '1d') or '${inputs.timeframe}' in ('24h', '1d')
            then date::date >= (select max(date::date) from sirens.subscribers) - interval '1 day'
        when '${inputs.timeframe.value}' = '30d' or '${inputs.timeframe}' = '30d'
            then date::date >= (select max(date::date) from sirens.subscribers) - interval '30 days'
        when '${inputs.timeframe.value}' = '90d' or '${inputs.timeframe}' = '90d'
            then date::date >= (select max(date::date) from sirens.subscribers) - interval '90 days'
        when '${inputs.timeframe.value}' = 'all' or '${inputs.timeframe}' = 'all'
            then true
        else
            date::date >= (select max(date::date) from sirens.subscribers) - interval '7 days'
    end
group by 1
order by 1
```


<LineChart
    data={daily_total}
    x=date
    y=total
    yAxisTitle="subscribers"
    yMin=0
    chartAreaHeight=280
/>

## Who gained and who lost

```sql movement_window
with recent as (
    select distinct date::date as date
    from sirens.subscribers
    order by 1 desc
    limit 2
)
select min(date) as earlier, max(date) as later from recent
```

Subscribers gained and lost between <Value data={movement_window} column=earlier/>
and <Value data={movement_window} column=later/>.

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

## Subscribers by channel

Audience breakdown across each Telegram alert channel, ranked from largest to smallest.

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

```sql latest_day
select max(date::date) as day from sirens.subscribers
```

Data as of <Value data={latest_day} column=day/>. The history starts on the day
counting was switched on. A day the snapshot could not reach most of the network
is left out entirely rather than recorded short, so a gap in the line means a
failed run, never lost subscribers.
