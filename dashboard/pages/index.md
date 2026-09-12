---
title: Sirens Network Analytics
---

<script>
    // Tooltip helpers. Backtick templates are avoided on purpose: the page is
    // parsed as markdown before Svelte sees it, and backticks read as code spans.
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

    // Same green/red/grey the movement chart uses, so a gain reads the same
    // everywhere on the page.
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

    // Mirrors the markup of Evidence's built-in tooltip so the custom ones do
    // not look grafted on.
    const tipHead = (text) => '<span style="font-weight: 600;">' + text + '</span>';

    const tipRow = (label, value) =>
        '<br/><span>' +
        label +
        ': </span><span style="float: right; margin-left: 10px;">' +
        value +
        '</span>';
</script>

Total audience reach and growth dynamics across all Sirens alert channels.
Snapshots are recorded throughout the day.

```sql headline
-- Comparisons are looked up by date rather than with lag(n): a missed snapshot
-- leaves a gap in the history, and counting rows back would measure against
-- the wrong day. Baselines are the most recent day at or before the target, so
-- a gap shifts the comparison instead of blanking the metric, which is why
-- every comparison carries the date it actually measured against.
with per_snapshot as (
    select
        date,
        date::date as day_date,
        sum(subscribers) as total
    from sirens.subscriber_snapshots
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
current_day as (
    select date, total
    from latest_per_day
    order by date desc
    limit 1
),
prev_day as (
    select day.date, day.total
    from latest_per_day day, current_day
    where day.date < current_day.date
    order by day.date desc
    limit 1
),
week_ago as (
    select day.date, day.total
    from latest_per_day day, current_day
    where day.date <= current_day.date - 7
    order by day.date desc
    limit 1
)
select
    current_day.total,
    current_day.total - prev_day.total as change_1d,
    (current_day.total - prev_day.total) / nullif(prev_day.total, 0)::double as change_1d_pct,
    strftime(prev_day.date, '%b %-d') as prev_day_label,
    current_day.total - week_ago.total as change_7d,
    (current_day.total - week_ago.total) / nullif(week_ago.total, 0)::double as change_7d_pct,
    strftime(week_ago.date, '%b %-d') as week_ago_label
from current_day
left join prev_day on true
left join week_ago on true
```

<BigValue
    data={headline}
    value=total
    title="Total Network Audience"
    comparison=change_1d_pct
    comparisonFmt=pct1
    comparisonTitle="({signed(headline[0].change_1d)}) since {headline[0].prev_day_label ?? 'previous run'}"
/>

<BigValue
    data={headline}
    value=change_7d
    fmt="+#,##0;-#,##0"
    title="7-Day Net Growth"
    comparison=change_7d_pct
    comparisonFmt=pct1
    comparisonTitle="vs {headline[0].week_ago_label ?? 'start of history'}"
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
    from sirens.subscriber_snapshots
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
yellow_start as (
    select min(date::date) as start_date
    from sirens.alerts_history
    where level = 'yellow'
      and channel_id is not null
      and channel_id != ''
),
daily_alerts as (
    select
        date::date as day_date,
        count(*) filter (where level = 'red') as red_alarms,
        count(*) filter (where level = 'yellow') as yellow_alarms
    from sirens.alerts_history
    where channel_id is not null
      and channel_id != ''
    group by 1
),
snapshots_24h as (
    select
        date,
        total,
        lag(date) over (order by date) as prev_date,
        strftime(date, '%b %-d, %H:%M') as label
    from per_snapshot
    where date >= (select max(date) from per_snapshot) - interval '24 hours'
),
view_24h as (
    select
        s.date,
        s.total,
        s.label,
        coalesce(count(a.date) filter (where a.level = 'red'), 0) as red_alarms,
        case
            when s.date::date < (select start_date from yellow_start) then null
            else coalesce(count(a.date) filter (where a.level = 'yellow'), 0)
        end as yellow_alarms
    from snapshots_24h s
    left join sirens.alerts_history a
           on a.channel_id is not null
          and a.channel_id != ''
          and a.date > coalesce(s.prev_date, s.date - interval '4 hours')
          and a.date <= s.date
    group by s.date, s.total, s.label
),
view_7d as (
    select
        l.date::timestamp as date,
        l.total,
        strftime(l.date, '%b %-d') as label,
        coalesce(a.red_alarms, 0) as red_alarms,
        case
            when l.date < (select start_date from yellow_start) then null
            else coalesce(a.yellow_alarms, 0)
        end as yellow_alarms
    from latest_per_day l
    left join daily_alerts a on a.day_date = l.date
    where l.date >= (select max(date) from latest_per_day) - interval '7 days'
),
view_30d as (
    select
        l.date::timestamp as date,
        l.total,
        strftime(l.date, '%b %-d') as label,
        coalesce(a.red_alarms, 0) as red_alarms,
        case
            when l.date < (select start_date from yellow_start) then null
            else coalesce(a.yellow_alarms, 0)
        end as yellow_alarms
    from latest_per_day l
    left join daily_alerts a on a.day_date = l.date
    where l.date >= (select max(date) from latest_per_day) - interval '30 days'
),
selected as (
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
-- The step back is over the points actually plotted, so on a day with no
-- snapshot the tooltip compares against the previous point it can name rather
-- than silently against the wrong day.
select
    date,
    total,
    label,
    total - lag(total) over (order by date) as change,
    (total - lag(total) over (order by date))
        / nullif(lag(total) over (order by date), 0)::double as change_pct,
    lag(label) over (order by date) as prev_label,
    red_alarms,
    yellow_alarms
from selected
order by 1
```

<LineChart
    data={daily_total}
    x=date
    y={["total", "red_alarms", "yellow_alarms"]}
    yAxisTitle="subscribers"
    yScale=true
    markers=true
    chartAreaHeight=280
    echartsOptions={{
        useUTC: true,
        legend: {
            show: true,
            top: 0
        },
        yAxis: [
            {
                type: 'value',
                name: 'subscribers',
                scale: true
            },
            {
                type: 'value',
                name: 'alarms',
                minInterval: 1,
                splitLine: { show: false }
            }
        ],
        series: [
            {
                name: 'total',
                yAxisIndex: 0,
                itemStyle: { color: '#2f9e44' },
                lineStyle: { color: '#2f9e44', width: 2 }
            },
            {
                name: 'red_alarms',
                yAxisIndex: 1,
                itemStyle: { color: '#e03131' },
                lineStyle: { color: '#e03131', width: 2 }
            },
            {
                name: 'yellow_alarms',
                yAxisIndex: 1,
                connectNulls: false,
                itemStyle: { color: '#fab005' },
                lineStyle: { color: '#fab005', width: 2 }
            }
        ],
        tooltip: {
            formatter: (params) => {
                const point = Array.isArray(params) ? params[0] : params;
                const row = daily_total[point.dataIndex] ?? {};
                let res = tipHead(row.label ?? point.axisValueLabel);
                res += tipRow('subscribers', num(row.total));
                if (row.prev_label) {
                    res += tipRow('vs ' + row.prev_label, delta(row.change, row.change_pct));
                }
                res += tipRow('<span style="color: #e03131;">●</span> red alarms', num(row.red_alarms));
                if (row.yellow_alarms !== null && row.yellow_alarms !== undefined) {
                    res += tipRow('<span style="color: #fab005;">●</span> yellow alarms', num(row.yellow_alarms));
                }
                return res;
            }
        }
    }}
/>

## Daily Channel Movement

```sql movement_window
with current_run as (
    select max(date) as current_time
    from sirens.subscriber_snapshots
),
previous_day_run as (
    select coalesce(
        (select max(date) from sirens.subscriber_snapshots where date::date < (select current_time::date from current_run)),
        (select min(date) from sirens.subscriber_snapshots)
    ) as prev_time
    from current_run
)
select
    strftime(previous_day_run.prev_time, '%B %-d, %Y %H:%M') as earlier,
    strftime(current_run.current_time, '%B %-d, %Y %H:%M') as later
from current_run, previous_day_run
```

Net subscriber change per channel between {movement_window[0].earlier} and {movement_window[0].later} (Kyiv time).

```sql movement
with current_run as (
    select max(date) as current_time
    from sirens.subscriber_snapshots
),
previous_day_run as (
    select coalesce(
        (select max(date) from sirens.subscriber_snapshots where date::date < (select current_time::date from current_run)),
        (select min(date) from sirens.subscriber_snapshots)
    ) as prev_time
    from current_run
),
later_counts as (
    select display_name, subscribers
    from sirens.subscriber_snapshots, current_run
    where date = current_run.current_time
),
earlier_counts as (
    select display_name, subscribers
    from sirens.subscriber_snapshots, previous_day_run
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

Audience distribution by channel, ranked by total subscriber count. Hovering a
bar shows how that channel moved over the same seven days the 7-Day Net Growth
metric measures.

```sql by_channel
-- The 7-day baseline is picked exactly the way the 7-Day Net Growth headline
-- picks it (most recent snapshot day at or before D-7), so the per-channel
-- changes in the tooltip add up to that metric.
with day_runs as (
    select
        date::date as day_date,
        max(date) as run_time
    from sirens.subscriber_snapshots
    group by 1
),
current_run as (
    select day_date, run_time
    from day_runs
    order by day_date desc
    limit 1
),
week_ago_run as (
    select day_runs.day_date, day_runs.run_time
    from day_runs, current_run
    where day_runs.day_date <= current_run.day_date - 7
    order by day_runs.day_date desc
    limit 1
),
later_counts as (
    select display_name, subscribers
    from sirens.subscriber_snapshots, current_run
    where date = current_run.run_time
),
earlier_counts as (
    select display_name, subscribers
    from sirens.subscriber_snapshots, week_ago_run
    where date = week_ago_run.run_time
)
select
    later.display_name,
    later.subscribers,
    later.subscribers - earlier.subscribers as change_7d,
    (later.subscribers - earlier.subscribers) / nullif(earlier.subscribers, 0)::double as change_7d_pct,
    (select strftime(day_date, '%b %-d') from week_ago_run) as week_ago_label
from later_counts later
left join earlier_counts earlier
       on earlier.display_name = later.display_name
order by later.subscribers desc
```

<BarChart
    data={by_channel}
    x=display_name
    y=subscribers
    swapXY=true
    yAxisTitle="subscribers"
    echartsOptions={{
        tooltip: {
            formatter: (params) => {
                const point = Array.isArray(params) ? params[0] : params;
                // swapXY puts the category in value[1]; name is the fallback.
                const name = point.value[1] ?? point.name;
                const row = Array.from(by_channel).find((d) => d.display_name === name) ?? {};
                return (
                    tipHead(name) +
                    tipRow('subscribers', num(point.value[0])) +
                    tipRow(
                        row.week_ago_label ? 'vs ' + row.week_ago_label : 'vs 7 days ago',
                        delta(row.change_7d, row.change_7d_pct)
                    )
                );
            }
        }
    }}
/>

## Weekly Growth Rate by Channel

Seven-day subscriber growth per channel, relative to each channel's own size.

```sql channel_growth
select
    display_name,
    subscribers,
    change_7d,
    change_7d_pct,
    week_ago_label,
    case
        when change_7d > 0 then 'Gained'
        when change_7d < 0 then 'Lost'
        else 'Unchanged'
    end as direction
from ${by_channel}
where change_7d is not null
order by change_7d_pct desc
```

<BarChart
    data={channel_growth}
    x=display_name
    y=change_7d_pct
    yFmt=pct1
    series=direction
    seriesColors={{Gained: '#2f9e44', Lost: '#e03131', Unchanged: '#adb5bd'}}
    swapXY=true
    sort=false
    yAxisTitle="7-day growth"
    emptySet=pass
    emptyMessage="No channel has a full week of history yet"
    echartsOptions={{
        tooltip: {
            formatter: (params) => {
                const point = Array.isArray(params) ? params[0] : params;
                const name = point.value[1] ?? point.name;
                const row = Array.from(channel_growth).find((d) => d.display_name === name) ?? {};
                return (
                    tipHead(name) +
                    tipRow(
                        row.week_ago_label ? 'vs ' + row.week_ago_label : 'vs 7 days ago',
                        delta(row.change_7d, row.change_7d_pct)
                    ) +
                    tipRow('subscribers', num(row.subscribers))
                );
            }
        }
    }}
/>

Data as of {movement_window[0].later} (Kyiv time). Historical tracking begins from the date
metrics collection was enabled. To ensure data integrity, incomplete snapshots
are omitted rather than recorded partially — any gaps in the trend line indicate
a missed run, not lost subscribers.
