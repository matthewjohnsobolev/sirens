---
title: Sirens Internal Statistics
---

How many people the Sirens alert channels reach. Every channel is counted once
a day, shortly after midnight Kyiv time.

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
    comparisonTitle="since yesterday"
/>

<BigValue
    data={headline}
    value=change_7d
    title="Change over the past week"
/>

## Growth over time

```sql daily_total
select
    date::date as date,
    sum(participants) as total
from sirens.channel_stats
group by 1
order by 1
```

<LineChart
    data={daily_total}
    x=date
    y=total
    yAxisTitle="subscribers"
    yMin=0
/>

## Who gained and who lost

```sql movement
-- The two most recent days in the history, whether or not they are adjacent on
-- the calendar: a night the snapshot failed is skipped rather than read as a
-- day when nothing happened. A channel that only appears on the later day is
-- left out - it has no previous count to be measured against.
with counts as (
    select display_name, date::date as date, participants
    from sirens.channel_stats
),
recent as (
    select distinct date from counts order by date desc limit 2
)
select
    later.display_name,
    later.participants - earlier.participants as change,
    case
        when later.participants > earlier.participants then 'Gained'
        when later.participants < earlier.participants then 'Lost'
        else 'Unchanged'
    end as direction
from counts later
join counts earlier
      on earlier.display_name = later.display_name
     and earlier.date = (select min(date) from recent)
where later.date = (select max(date) from recent)
order by change, later.display_name
```

```sql movement_window
with recent as (
    select distinct date::date as date
    from sirens.channel_stats
    order by 1 desc
    limit 2
)
select min(date) as earlier, max(date) as later from recent
```

Subscribers gained and lost between <Value data={movement_window} column=earlier/>
and <Value data={movement_window} column=later/>.

<BarChart
    data={movement}
    x=display_name
    y=change
    series=direction
    seriesColors={{Gained: '#2f9e44', Lost: '#e03131', Unchanged: '#adb5bd'}}
    swapXY=true
    sort=false
    labels=true
    labelSize=10
    chartAreaHeight=700
/>

## Subscribers by channel

```sql by_channel
select
    display_name,
    participants
from sirens.channel_stats
where date::date = (select max(date::date) from sirens.channel_stats)
order by participants desc
```

<BarChart
    data={by_channel}
    x=display_name
    y=participants
    swapXY=true
    labels=true
    labelSize=10
    chartAreaHeight=700
/>

```sql latest_day
select max(date::date) as day from sirens.channel_stats
```

Data as of <Value data={latest_day} column=day/>. The history starts on the day
counting was switched on. A day the snapshot could not reach most of the network
is left out entirely rather than recorded short, so a gap in the line means a
failed run, never lost subscribers.
