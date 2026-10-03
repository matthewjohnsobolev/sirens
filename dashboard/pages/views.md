---
title: Alert Views
---

How quickly each region reacts to an air raid alert. Every alert is sampled
15 s, 30 s, 1 min, 5 min, 15 min and 30 min after it is posted, until its
all-clear goes out. To compare regions of different size, views are shown as
reach: the share of the channel's subscribers (at the time of the alert) who
have seen the alert.

```sql alert_reach
with alert_views as (
    select
        posted_at::timestamp as posted_at,
        location,
        display_name,
        checkpoint_s,
        views
    from sirens.message_views
    where event_type = 'air_raid_alert'
      and year(posted_at::timestamp) > 1970
),
snapshots as (
    select channel_key, date::timestamp as snapshot_at, subscribers
    from sirens.subscriber_snapshots
),
first_snapshot as (
    select channel_key, arg_min(subscribers, snapshot_at) as subscribers
    from snapshots
    group by 1
)
select
    v.*,
    coalesce(s.subscribers, f.subscribers) as subscribers,
    v.views / nullif(coalesce(s.subscribers, f.subscribers), 0)::double as reach
from alert_views v
asof left join snapshots s
    on v.location = s.channel_key and v.posted_at >= s.snapshot_at
left join first_snapshot f on f.channel_key = v.location
```

```sql region_ranks
select location, median(reach) as reach_1m
from ${alert_reach}
where checkpoint_s = 60
group by 1
```

```sql reach_by_checkpoint
with checkpoints(checkpoint_s, checkpoint_label) as (
    values
        (15, '15 s'),
        (30, '30 s'),
        (60, '1 min'),
        (300, '5 min'),
        (900, '15 min'),
        (1800, '30 min')
)
select
    a.display_name,
    coalesce(r.reach_1m, 0) as reach_1m,
    a.checkpoint_s,
    c.checkpoint_label,
    median(a.reach) as reach
from ${alert_reach} a
join checkpoints c using (checkpoint_s)
left join ${region_ranks} r using (location)
group by all
```

```sql reach_by_day
select
    a.display_name,
    coalesce(r.reach_1m, 0) as reach_1m,
    date_trunc('day', a.posted_at) as day,
    strftime(date_trunc('day', a.posted_at), '%d %b') as day_label,
    median(a.reach) as reach
from ${alert_reach} a
left join ${region_ranks} r using (location)
where a.checkpoint_s = 60
group by all
```

```sql region_summary
select
    location,
    display_name,
    count(distinct posted_at) filter (where checkpoint_s = 15) as alerts,
    max(subscribers) as subscribers,
    median(views) filter (where checkpoint_s = 60) as views_1m,
    median(reach) filter (where checkpoint_s = 15) as reach_15s,
    median(reach) filter (where checkpoint_s = 60) as reach_1m,
    median(reach) filter (where checkpoint_s = 300) as reach_5m,
    median(reach) filter (where checkpoint_s = 1800) as reach_30m,
    '/' || location as link
from ${alert_reach}
group by 1, 2
```

## Reaction by Region

Median reach of an alert at each checkpoint, fastest regions (by reach at
1 min) on top. Later checkpoints only include alerts that were still on.

<Heatmap
    data={reach_by_checkpoint}
    x=checkpoint_label
    xSort=checkpoint_s
    y=display_name
    ySort=reach_1m
    ySortOrder=desc
    value=reach
    valueFmt=pct0
    emptySet=pass
    emptyMessage="No views sampled yet"
/>

## Reaction over Time

Median reach 1 minute after an alert, day by day. A region turning lighter
means fewer people react to its alerts right away.

<Heatmap
    data={reach_by_day}
    x=day_label
    xSort=day
    y=display_name
    ySort=reach_1m
    ySortOrder=desc
    value=reach
    valueFmt=pct0
    nullsZero=false
    emptySet=pass
    emptyMessage="No views sampled yet"
/>

<DataTable data={region_summary} rows=all sort="reach_1m desc" link=link emptySet=pass emptyMessage="No views sampled yet">
    <Column id=display_name title="City" />
    <Column id=alerts title="Alerts" />
    <Column id=subscribers title="Subscribers" fmt=num0 />
    <Column id=views_1m title="Views at 1 min (median)" fmt=num0 />
    <Column id=reach_15s title="Reach 15 s" fmt=pct0 />
    <Column id=reach_1m title="Reach 1 min" fmt=pct0 />
    <Column id=reach_5m title="Reach 5 min" fmt=pct0 />
    <Column id=reach_30m title="Reach 30 min" fmt=pct0 />
</DataTable>
