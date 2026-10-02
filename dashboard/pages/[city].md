---
# No title: Evidence would use it for the breadcrumb, which should read
# Home > <city>. og.title still gives the tab a name.
hide_title: true
og:
    title: City Drill-down
breadcrumb: "select display_name as breadcrumb from sirens.subscriber_snapshots where channel_key = '${params.city}' limit 1"
---

<style>
    :global(h2.markdown) {
        margin-top: 2.25rem !important;
        margin-bottom: 0.5rem !important;
    }
    :global(.chart-container) {
        margin-bottom: 2rem !important;
    }
</style>

<script>
    // Same tooltip helpers as the main page (see pages/index.md); duplicated
    // because a page script cannot be shared between routes here. Backtick
    // templates are avoided on purpose: the page is parsed as markdown first.
    const num = (value) =>
        value === null || value === undefined ? 'n/a' : Number(value).toLocaleString('en-US');

    const signed = (value) =>
        value === null || value === undefined
            ? 'n/a'
            : (value > 0 ? '+' : value < 0 ? '-' : '') + Math.abs(value).toLocaleString('en-US');

    const signedPct = (value) =>
        value === null || value === undefined
            ? null
            : (value > 0 ? '+' : value < 0 ? '-' : '') + (Math.abs(value) * 100).toFixed(1) + '%';

    const delta = (change, pct) => {
        if (change === null || change === undefined) return 'no data';
        const color = change > 0 ? '#2f9e44' : change < 0 ? '#e03131' : '#868e96';
        const percent = signedPct(pct);
        return (
            '<span style="color: ' +
            color +
            '">' +
            signed(change) +
            (percent ? ' (' + percent + ')' : '') +
            '</span>'
        );
    };

    const tipHead = (text) => '<span style="font-weight: 600;">' + text + '</span>';

    const tipRow = (label, value) =>
        '<br/><span>' +
        label +
        ': </span><span style="float: right; margin-left: 10px;">' +
        value +
        '</span>';
</script>

```sql city
-- One row for the city in the URL; the header and the metric tiles read from it.
with snapshot_days as (
    select
        date::date as day_date,
        max(date) as run_time
    from sirens.subscriber_snapshots
    group by 1
),
current_run as (
    select day_date, run_time
    from snapshot_days
    order by day_date desc
    limit 1
),
prev_run as (
    select d.day_date, d.run_time
    from snapshot_days d, current_run
    where d.day_date < current_run.day_date
    order by d.day_date desc
    limit 1
),
week_ago_run as (
    select d.day_date, d.run_time
    from snapshot_days d, current_run
    where d.day_date <= current_run.day_date - 7
    order by d.day_date desc
    limit 1
),
later_counts as (
    select channel_key, display_name, subscribers
    from sirens.subscriber_snapshots, current_run
    where date = current_run.run_time
),
ranked as (
    select
        channel_key,
        display_name,
        subscribers,
        rank() over (order by subscribers desc) as audience_rank,
        count(*) over () as city_count
    from later_counts
),
prev_counts as (
    select channel_key, subscribers
    from sirens.subscriber_snapshots, prev_run
    where date = prev_run.run_time
),
week_counts as (
    select channel_key, subscribers
    from sirens.subscriber_snapshots, week_ago_run
    where date = week_ago_run.run_time
),
alerts_7d as (
    select
        coalesce(sum(a.red_alerts), 0) as red_alerts,
        coalesce(sum(a.yellow_alerts), 0) as yellow_alerts
    from sirens.alerts_history a, current_run
    where a.location = '${params.city}'
      and a.date::date > current_run.day_date - 7
      and a.date::date <= current_run.day_date
)
select
    r.channel_key,
    r.display_name,
    r.subscribers,
    r.audience_rank,
    r.city_count,
    r.subscribers - p.subscribers as change_1d,
    (r.subscribers - p.subscribers) / nullif(p.subscribers, 0)::double as change_1d_pct,
    strftime(prev_run.day_date, '%b %-d') as prev_day_label,
    r.subscribers - w.subscribers as change_7d,
    (r.subscribers - w.subscribers) / nullif(w.subscribers, 0)::double as change_7d_pct,
    strftime(week_ago_run.day_date, '%b %-d') as week_ago_label,
    alerts_7d.red_alerts,
    alerts_7d.yellow_alerts
from ranked r
left join prev_counts p on p.channel_key = r.channel_key
left join week_counts w on w.channel_key = r.channel_key
left join prev_run on true
left join week_ago_run on true
left join alerts_7d on true
where r.channel_key = '${params.city}'
```

{#if city.length === 0}

No data for this city. Pick one from a chart on the [dashboard](/).

{:else}

# {city[0].display_name}

Audience and alert activity for this city. Ranked #{city[0].audience_rank} of
{city[0].city_count} cities by subscribers.

<BigValue
    data={city}
    value=subscribers
    fmt="#,##0"
    title="Subscribers"
    comparison=change_1d_pct
    comparisonFmt=pct1
    comparisonTitle="({signed(city[0].change_1d)}) since {city[0].prev_day_label ?? 'previous run'}"
/>

<BigValue
    data={city}
    value=change_7d
    fmt="+#,##0;-#,##0"
    title="7-Day Net Growth"
    comparison=change_7d_pct
    comparisonFmt=pct1
    comparisonTitle="vs {city[0].week_ago_label ?? 'start of history'}"
/>

<BigValue data={city} value=red_alerts fmt="#,##0" title="Red Alerts (7D)" />

<BigValue data={city} value=yellow_alerts fmt="#,##0" title="Yellow Alerts (7D)" />

<ButtonGroup name=timeframe defaultValue="7d">
    <ButtonGroupItem valueLabel="24H" value="24h" />
    <ButtonGroupItem valueLabel="7D" value="7d" />
    <ButtonGroupItem valueLabel="30D" value="30d" />
    <ButtonGroupItem valueLabel="ALL" value="all" />
</ButtonGroup>

## Subscribers

```sql city_trend
with per_snapshot as (
    select
        date,
        date::date as day_date,
        subscribers as total
    from sirens.subscriber_snapshots
    where channel_key = '${params.city}'
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
        total,
        strftime(date, '%b %-d, %H:%M') as label
    from per_snapshot
    where date >= (select max(date) from per_snapshot) - interval '24 hours'
),
view_7d as (
    select
        date::timestamp as date,
        total,
        strftime(date, '%b %-d') as label
    from latest_per_day
    where date >= (select max(date) from latest_per_day) - interval '7 days'
),
view_30d as (
    select
        date::timestamp as date,
        total,
        strftime(date, '%b %-d') as label
    from latest_per_day
    where date >= (select max(date) from latest_per_day) - interval '30 days'
),
view_all as (
    select
        date::timestamp as date,
        total,
        strftime(date, '%b %-d') as label
    from latest_per_day
),
chosen_timeframe as (
    select case
        when '${inputs.timeframe}' in ('24h', '7d', '30d', 'all')
            then '${inputs.timeframe}'
        when '${inputs.timeframe.value}' in ('24h', '7d', '30d', 'all')
            then '${inputs.timeframe.value}'
        else '7d'
    end as tf
),
selected as (
    select v.* from view_24h v, chosen_timeframe c where c.tf = '24h'
    union all
    select v.* from view_7d v, chosen_timeframe c where c.tf = '7d'
    union all
    select v.* from view_30d v, chosen_timeframe c where c.tf = '30d'
    union all
    select v.* from view_all v, chosen_timeframe c where c.tf = 'all'
)
select
    date,
    total,
    label,
    total - lag(total) over (order by date) as change,
    (total - lag(total) over (order by date))
        / nullif(lag(total) over (order by date), 0)::double as change_pct,
    lag(label) over (order by date) as prev_label
from selected
order by 1
```

<LineChart
data={city_trend}
x=date
y=total
lineColor="#2f9e44"
yAxisTitle="subscribers"
yFmt="#,##0"
yScale=true
markers=true
chartAreaHeight=280
echartsOptions={{
        useUTC: true,
        series: [
            {
                itemStyle: { color: '#2f9e44' },
                lineStyle: { color: '#2f9e44', width: 2 }
            }
        ],
        tooltip: {
            formatter: (params) => {
                const point = Array.isArray(params) ? params[0] : params;
                const row = city_trend[point.dataIndex] ?? {};
                return (
                    tipHead(row.label ?? point.axisValueLabel) +
                    tipRow('subscribers', num(point.value[1] ?? row.total)) +
                    (row.prev_label
                        ? tipRow('vs ' + row.prev_label, delta(row.change, row.change_pct))
                        : '')
                );
            }
        }
    }}
/>

## Alerts

Yellow and red alerts recorded for this city over the same window. The 24H view
shows four-hour buckets; longer views sum by day.

```sql city_alerts
-- The axis is generated rather than taken from the alert rows: a window with a
-- single alert would otherwise collapse the time axis around one bar, and a
-- quiet stretch would read as missing data instead of zero alerts. The 24H view
-- steps through the same 4-hour buckets the export writes. 7D and 30D cover
-- exactly that many days, matching the 7-day alert tiles above.
with latest as (
    select max(date) as run_time
    from sirens.subscriber_snapshots
),
chosen_timeframe as (
    select case
        when '${inputs.timeframe}' in ('24h', '7d', '30d', 'all')
            then '${inputs.timeframe}'
        when '${inputs.timeframe.value}' in ('24h', '7d', '30d', 'all')
            then '${inputs.timeframe.value}'
        else '7d'
    end as tf
),
bounds as (
    select
        c.tf,
        case c.tf
            when '24h' then time_bucket(interval '4 hours', l.run_time, timestamp '2000-01-01')
                - interval '24 hours'
            when '7d' then l.run_time::date::timestamp - interval '6 days'
            when '30d' then l.run_time::date::timestamp - interval '29 days'
            else (
                select min(date::date)::timestamp
                from sirens.subscriber_snapshots
                where channel_key = '${params.city}'
            )
        end as first_slot,
        case c.tf
            when '24h' then time_bucket(interval '4 hours', l.run_time, timestamp '2000-01-01')
            else l.run_time::date::timestamp
        end as last_slot,
        case c.tf
            when '24h' then interval '4 hours'
            else interval '1 day'
        end as step
    from latest l, chosen_timeframe c
),
slots as (
    select
        tf,
        unnest(generate_series(first_slot, last_slot, step)) as slot
    from bounds
)
select
    s.slot as date,
    case
        when s.tf = '24h' then strftime(s.slot, '%b %-d, %H:%M')
        else strftime(s.slot, '%b %-d')
    end as label,
    coalesce(sum(a.yellow_alerts), 0) as "Yellow Alerts",
    coalesce(sum(a.red_alerts), 0) as "Red Alerts"
from slots s
left join sirens.alerts_history a
       on a.location = '${params.city}'
      and case
            when s.tf = '24h' then a.date = s.slot
            else a.date::date = s.slot::date
          end
group by 1, 2
order by 1
```

<BarChart
data={city_alerts}
x=date
y={['Yellow Alerts', 'Red Alerts']}
type=stacked
colorPalette={['#eab308', '#ef4444']}
fillOpacity=0.65
yAxisTitle="alerts"
chartAreaHeight=240
emptySet=pass
emptyMessage="No alerts recorded for this city in the selected window"
echartsOptions={{
        useUTC: true,
        yAxis: { minInterval: 1 },
        tooltip: {
            trigger: 'axis',
            formatter: (params) => {
                const point = Array.isArray(params) ? params[0] : params;
                const row = city_alerts[point.dataIndex] ?? {};
                return (
                    tipHead(row.label ?? point.axisValueLabel) +
                    tipRow('<span style="color: #eab308;">●</span> Yellow Alerts', num(row['Yellow Alerts'])) +
                    tipRow('<span style="color: #ef4444;">●</span> Red Alerts', num(row['Red Alerts']))
                );
            }
        }
    }}
/>


## Alert Views

Median views of the alert and of its all-clear at each checkpoint after
posting. An alert is only sampled until its all-clear goes out, so later
checkpoints cover only the alerts still on (see "Alerts still on").

```sql city_checkpoint_stats
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
    from sirens.message_views
    where location = '${params.city}'
      and year(posted_at::timestamp) > 1970
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

<LineChart
    data={city_checkpoint_stats}
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

<DataTable data={city_checkpoint_stats} rows=all sort="checkpoint_s asc" sortable=false emptySet=pass emptyMessage="No views sampled for this city yet">
    <Column id=checkpoint_label title="After posting" />
    <Column id=open_alerts title="Alerts still on" />
    <Column id=open_share title="Share of alerts" fmt=pct0 />
    <Column id=alert_views title="Alert views (median)" fmt=num0 />
    <Column id=all_clears title="All-clears" />
    <Column id=all_clear_views title="All-clear views (median)" fmt=num0 />
</DataTable>

{/if}
