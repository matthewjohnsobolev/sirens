---
title: Alert Views
---

How many people see an air raid alert while it is still on, city by city.
Every alert is sampled 15 s, 30 s, 1 min, 5 min, 15 min and 30 min after it is
posted, but only until its all-clear goes out, so later checkpoints cover only
the longer alerts.

```sql view_cities
select 'all' as location, 'All cities' as display_name, 0 as sort_order
union all
select distinct location, display_name, 1 as sort_order
from sirens.message_views
where year(posted_at::timestamp) > 1970
order by sort_order, display_name
```

<Dropdown
    data={view_cities}
    name=view_city
    value=location
    label=display_name
    defaultValue="all"
    order="sort_order, display_name"
    title="City"
/>

```sql city_views
with selected as (
    select case
        when '${inputs.view_city.value}' not in ('', 'undefined', 'null')
            then '${inputs.view_city.value}'
        when '${inputs.view_city}' not in ('', 'undefined', 'null', '[object Object]')
            then '${inputs.view_city}'
        else 'all'
    end as location
)
select v.*
from sirens.message_views v, selected
where year(v.posted_at::timestamp) > 1970
  and (selected.location = 'all' or v.location = selected.location)
```

```sql checkpoint_stats
with checkpoints(checkpoint_s, checkpoint_label) as (
    values
        (15, '15 s'),
        (30, '30 s'),
        (60, '1 min'),
        (300, '5 min'),
        (900, '15 min'),
        (1800, '30 min')
),
stats as (
    select
        checkpoint_s,
        count(*) filter (where event_type = 'air_raid_alert') as open_alerts,
        median(views) filter (where event_type = 'air_raid_alert') as alert_views,
        count(*) filter (where event_type = 'air_raid_alert_cancelled') as all_clears,
        median(views) filter (where event_type = 'air_raid_alert_cancelled') as all_clear_views
    from ${city_views}
    group by 1
)
select
    c.checkpoint_s,
    c.checkpoint_label,
    coalesce(s.open_alerts, 0) as open_alerts,
    coalesce(s.open_alerts, 0) / nullif(max(coalesce(s.open_alerts, 0)) over (), 0)::double as open_share,
    s.alert_views,
    coalesce(s.all_clears, 0) as all_clears,
    s.all_clear_views
from checkpoints c
left join stats s using (checkpoint_s)
order by c.checkpoint_s
```

## Views by Checkpoint

Median views of the alert (while still on) and of the all-clear at each
checkpoint.

<LineChart
    data={checkpoint_stats}
    x=checkpoint_label
    y={['alert_views', 'all_clear_views']}
    yFmt=num0
    sort=false
    markers=true
    colorPalette={['#ef4444', '#22c55e']}
    chartAreaHeight=220
    emptySet=pass
    emptyMessage="No views sampled yet"
/>

<DataTable data={checkpoint_stats} rows=all sort="checkpoint_s asc" sortable=false emptySet=pass emptyMessage="No views sampled for this city yet">
    <Column id=checkpoint_label title="After posting" />
    <Column id=open_alerts title="Alerts still on" />
    <Column id=open_share title="Share of alerts" fmt=pct0 />
    <Column id=alert_views title="Alert views (median)" fmt=num0 />
    <Column id=all_clears title="All-clears" />
    <Column id=all_clear_views title="All-clear views (median)" fmt=num0 />
</DataTable>
