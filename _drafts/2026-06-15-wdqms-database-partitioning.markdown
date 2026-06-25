---
layout: post
title:  "WDQMS database review (partitioning)"
date:   2026-06-15 12:06:51 +0100
categories: wqdms
tags: wdqms 
---

This post describes the reasons behind the WDQMS database restructuring, and the process of implementing it.

Since its launch in 2019, the database behind WDQMS has grown steadily, with several tables now reaching billions of records and occupying hundreds of gigabytes of space.

![WDQMS table growth]( {{ '/assets/images/grafana-wdqms-database-dashboard_2026.png' | relative_url }}  )
*WDQMS database table growth over 6 months in June 2026. The largest table has more than 6bn records taking 1.75tb of space.*

At the same time, WDQMS had become more busy overall, with more users' browsers needing an increased amount of map-tiles and automated processes 
making use of the data supplied by WDQMS's API, likely sparked by AI web scraping.

![WDQMS API usage]( {{ '/assets/images/wdqms-API-usage-2026.png' | relative_url }}  )
*WDQMS API usge in June 2026. The sixhour NWP synop data is accessed at a rate of around 10 requests per second, likey due to AI scraping.*

## Signs of age 

While the most time-critical parts of the system, the map-tile and API downloads endpoints, kept having satisfactory performance in the range of 300 ms response times, the system started showing the limits of its current database schema 
in other areas. First, the queries delivering data to the time-series plots in the pop-up started taking upwards 30 seconds at times, resulting in inaccceptable waiting time for users.
Second, system operators informed the development team of infrequent yet persistent data-processing job failures. The metrics added in the [observability release]({% post_url 2025-11-01-wdqms-observability %})  showed that these failures are related to data-loading processes exceeding the maximum allowed pod runtime of kubernetes,
during times of high database load.

Another key consideration was the desire to improve overall data-management, such as  backup, restore and archiving, which were taking several days to complete for complete table exports under the current architecture (ECMWF internal backup not relying on complete exports do keep the database backuped quickly and regularly).

## Current database schema and data-processing architecture

WDQMS uses PostgreSQL, currently in version 13, together with PostGIS spatial extensions, as database. 
Observations provided by NWP centers are matched to the station table (linked to OSCAR/Surface), but otherwise stored as-is in an observation table per observation type, and then aggregated by custom Python logic into six-hour, daily and monthly periods.
The result of the aggeregation is materialized in dedicated tables for six-hour, daily and monthly aggregations by data-processing jobs. 
Data and aggregation status for a particular aggregation-type, period and center is referenced via a *period* model. 

For example, the *SixHourPeriod* for file-type=SYNOP, center=JMA and date='2020-02-23:18:00:00+00' references data for the 18h 2020-02-23 period of SYNOP data from JMA. 
The _id_ of the period model is a foreign key in the aggegation tables, allowing fast access to the data to the tile-server to which 
the _period_id_ is supplied by the frontend. This design allows the database to use a single index to access the most performance critical data, 
and can also be used to remove data consistently from the database by deleting periods which triggers consistent and cascading data removal from aggregation tables.


![WDQMS database schema synopsixhourperiod]( {{ '/assets/images/wdqms-synopobservationsbysixhourperiod-schema-cropped.png' | relative_url }}  ){: .center-image width="33%"}
*ERD of the synopsixhour aggegation table. Aggregated observations have a foreign key on the corresponding station and period. Note the varchar(10) type for center.*

Large tables (observation and aggregation tables for the SYNOP, GBON-SYNOP and Marine types) are partitioned by _var_id_.

The schema of two databases tables is described in detail below. 
These tables are representative of the other large tables with other observation types and aggegations.

### The synopobservationsbysixhour table as an example of an aggregation table

The aggregation tables are indexed to support three main functions. 
First, an index on _(period_id)_ to generate tiles for the map. The map client passes the period_id as a parameter to the map layer being shown.
Second, an index on _(date)_ to download data from the API. Parameters values date, variable and center are passed to the API by the user.  
Third, the a composite index on _(station_id,date,center)_ to provide time series data to the station popup.

![WDQMS database synopsixhourperiod indexes]( {{ '/assets/images/wdqms-sixhoursynopobservations-indexes.png' | relative_url }}  ){: .center-image width="33%"}
*Indexes of the sixhour aggegation table. Index for primary key not shown. Note the non-descriptive index names dating to an early Django version.*


### The synopobservations table as an example of a raw observations table

The observations tables have an index for each the sixhour, daily and monthly periods, 
as well as an index on (station_id,date,center). The latter is used to provide time-series data to the six-hour quality station popup,
whereas the former are used to to obtain raw observations during the aggregations by sixhour, daily or monthly periods.

![WDQMS databse schema synopsixhourperiod]( {{ '/assets/images/wdqms-synopobservations-schema-cropped.png' | relative_url }}  ){: .center-image width="33%"}
*ERD of the synop observation table.*


![WDQMS database synopsixhourperiod indexes]( {{ '/assets/images/wdqms-synopobservation-indexes.png' | relative_url }}  ){: .center-image width="33%"}
*Indexes of the synop observations aggegation table. Index for primary key not shown. Note the non-descriptive index names dating to an early Django version.*


## Analysis 

This section analyzes the current system behaviour in terms of data-processing cron-job failures, overall datamanagement and time-series endpoint performance. 

### Data-processing failures

Both fetch-data and data-aggregation jobs process multiple files or periods in a single invocation. Jobs are implemented as Kubernetes cron-jobs each running in a separate pod.
If a large number of files or periods are processed at a time of high database load, the maximum pod execution time is reached and the pod terminated by the cluster.

Metrics tracking the runtime of synop observations fetch data job, show that they take between 30-180 minutes to complete. Similarly, the synop aggregation jobs take between 20-120 minutes to complete. 
The maxmium runtime is consistent with the 3h and respective 2h maximum runtime setting in the k8s configuration for fetch data and aggregation cron-jobs.

Database insertion time into the synop observations table ranges between a 10-200 records per second, with the average towards the lower (slower) end. The sixhour synop observations table has a similar pattern.

![WDQMS database insertion time]( {{ '/assets/images/wdqms-synopobservations-insertion-time.png' | relative_url }}  ){: .center-image width="50%"}
*Insertion time into synopobservations table per NWP file together with records inserted per second.*


The **reason for the data-processing failures** is therefore clearly a combination of **slow database inserts** and **numerous files or periods to process** in a single invocation. 

There are two obvious solutions to addressing the data-processing failures. One is to increase the maximum allowed processing time, the other one is to speed up database inserts.
The former is not a solution, as the system is nearing a point where **data inflow exceeds the database insertion capacity**. The 4 NWP centers produce 4 daily SYNOP files, which take on average 1h to insert and run sequentially.
This means 16 out of 24 hours are already spent inserting data.
Therefore the solution must be to speed up database inserts.

A performance experiment confirmed that index maintenance is responsible for slowliness of bulk inserts. When creating a fully partitioned but empty copy of the sixhour synop observations table, and subsquently filling it 
in batches of 7000 records with the original table (having ~2.5b records), the insert performance went from an inital 400 records/second to a 20 records/second after around 20% of records inserted. Without additional indexes 
(only keeping the one for the primary key) the insert speed increased to 45000 records/second.

### Data-management

The current partitioning schema by variable divides the data roughly equally and has the advantage of fast access for performance critical queries, but each partition keeps growing as time passes. This makes creating or restoring a backup difficult, as all partitions need to be 
exported for a complete backup. Under a date based partitioning schema, only the latest partition would have to be backuped. This is because WDQMS does not update or delete observations or aggregations once they are inserted into the database.
The current partitioning schema also does not allow to archive old data easily, or potentially move older and less frequently accessed data to slower/cheaper storage media.


![WDQMS synop observation partitions]( {{ '/assets/images/wdqms-synopobs-partitions.png' | relative_url }}  ){: .center-image width="33%"}
*Current partitioning schema of the synopobservations table.*


### Time-series queries

Time-series queries deliver data to the popup window of individual stations and show the last 30 days of aggregated availability or timeliness in a time-series chart. 
In the case of six-hour quality with a center selected, the timeseries chart plots the actual quality of the observations, requiring a query of the observations table, the biggest table in the database.

![WDQMS availability timeseries of Ghardaia station]( {{ '/assets/images/wdqms-ghardaia-all-centers.png' | relative_url }}  ){: .center-image width="50%"}
*Availability timeseries of Ghardaia station.*

For the time-series, the nr_expected, nr_received, center and date attributes are needed, whereas for the quality the avg_bg_dep, date and center and for timeliness the timeliness and ng_negative_timeliness values are shown.
Selection of data is done by date range, list of station ids (station ids of the same station vary over time) and by center (in case of a timeseries for an single center view).


{% highlight sql %}
SELECT id,var_id,avg_bg_dep,date,center,nr_expected,nr_received
FROM   wdqmsapi_synopobservationbysixhourperiod
WHERE  (date >= '2025-07-27 21:40:10.853449440+00:00'
        AND date <= '2025-08-26 21:40:10.853449440+00:00'
        AND station_id IN (14198,56150,47198,35860)
        AND var_id IN (58));</code>
{%endhighlight%}
*Example of a time-series SQL query for a sixhour availability popup*

A composite index on (station_id, date, center) was created in support of time-series queries. As is evident from the query above, the first and the second level of this index are queried by range, 
as station_id is a list (typically ranging from 1-5 entries) and date is a range (of currently 30 days). The last element of the index is only used if a time-series for an individual center is requested.

Query planner statistics produced with EXPLAIN (ANALYZE, COSTS, BUFFERS, VERBOSE) show a planning time of ~250ms and overall execution time of 10000ms, with 500 blocks (~4MB) read, of which only 3 were cached and 497 had to be fetched from disk for 480 rows (4 centers x 4 files x 30 days).
The execution plan shows that the planner correctly identifies the relevant partition and uses the composite index. 
There is evidence for an **IO issue** in the statistics, as 4MB should not take 10s to load, even with random access on rotating disk media.

![WDQMS Query planner statistics time series]( {{ '/assets/images/wdqms-query-planner-time-series.png' | relative_url }}  ){: .center-image width="50%"}
*Query planner statistics*

Experiments were conducted to find out if better indexes and additional partitioning improves the time-series 
queries while maintaining acceptable performance for tile-queries, and whether the storage plays a role in the slow queries.
For this, copies of the synopobservationsbysixhourperiod, synopstations and sixhourperiod tables were loaded into three test servers 
in the European Weather Cloud (cores: 8, Memory: 32 GiB, Storage: 3.0TiB, Pg14 on Ubuntu), WDQMS test database (Freebsd Jail on ECMWF Cluster, Pg18), 
and Google Computing Cloud (c3-standard-4, cores: 4 vCPUs, Memory: 16 GiB, Storage: 4.0TiB SSD, Pg17 on Debian).

The experiments consists of running on both test servers the same 100 randomly generated time-series and tile queries 
on different index and partitoning configurations, preceeded by OS page cache pruning and database restarts.

| Server      | Partitioning | Index    | avg sec/query | 
| ----------- | ----------- |  ----------- | ----------- |  
| Google (SSD) | By variable       |  (station_id,date,center)      | 0.15 |
| EWC | By variable   |  (station_id,date,center)      | 18.02 |
| EWC | By variable   |  (station_id,date)      | 11.88 |
| EWC | By variable   |  (id_station,date)      |  |
| EWC | By variable and date (year)  |  (station_id,date)      | 7.13 |
| HPC | By variable  |  (station_id,datec,enter)      | 11.79333333 |

The results indicate a random page access issue in both the EWC and HPC environments.
While there are differences in performance between different partitioning schemas and indexes, 
the **primary reason for the slow time-series queries is slow random page access**.

![WDQMS Query planner statistics time series]( {{ '/assets/images/wdqms-time-series-HPC-GCC-side-by-side.png' | relative_url }}  ){: .center-image width="75%"}
*Side by side comparison the query performance in HPC and GCC environments. The HPC environment takes 8s to load only 4MB of blocks.*

Other findings are that a smaller 2-level composite index, or a sub-partitioning by date in the 2nd leve, have performance advantages,
likely due to the smaller index side and consequent decreased IO during index traversal.
On the other hand, selecting a more limited number of columns has no noticable effect on performance. This opens up the possibility to consolidate queries for availability, timeliness and quality.
 
## Proposed new schema and database

The findings above indicate that a sub-partition schema for the largest tables, 
together with a consolidation of indexes on a random page access optimized storage medium will address the 
performance, outage and data-management issues discussed above.


### New partitioning schema

Under the new partitioning schema the already existing partitions by _var_id_ will be further partitioned by
_date_ with each partition holding one year's worth data. The new schema will be applied to all tables already partitioned by _var_id_.
This results in smaller partitions and indexes, limits table growth and improves data-management, while 
maintaining a logical data organization that is aligned with how WDQMS exposes data, which is by variable and 
period of time. The partitioning logic ensures that queries in principle need to scan a single partition, avoiding having to query 
multiple tables and merging results.

![WDQMS new partitioning schema]( {{ '/assets/images/wdqms_new_schema.png' | relative_url }}  ){: .center-image width="50%"}
*New partitioning schema. The existing partitions by variable are further partitioned by date.*

#### Tile query optimization for sub-partitioning (1/2)

The time-series and API download queries explicitely include _var_id_ and _date_ therefore supplying key 
information to the query planner to allow it to only scan a single partition. However, the tile-server queries
supply _var_id_ and _period_id_ and to not provide a _date_ parameter. While under the current partitioning schema the var_id is sufficient to route 
the query to the right partition and then use an index on period_id to locate records, the lack of date information
means that in the new sub-partitioned schema all sub-partitions corresponding to the var_id supplied need to be queries and results merged.

![all sub-partitions scanned without date]( {{ '/assets/images/wdqms-query-plan-without-date.png' | relative_url }}  ){: .center-image width="50%"}
*All sub-partitions need to be queried when date information is not provided.*



One solution would be to sub-partition by _period_id_ instead of date, but this is not practical for two reasons.
First, _period_id_ do not follow the same sort order as _date_, since periods are not always inserted into the systme 
by chronological order, making it impossible to express lower and upper bounds corresponding to a year. 
Second, _period_id_ are mpt expressive enough to provide for readily understandable partitions aligned with business logic.


The solution adopted by WDQMS is to add a new select clause to the tile-server queries which explicitely supplies a _date_ information, allowing
the query planner to identify the right partition. It's value can be computed in a light-weight subquery resolving _period_id_ to _date_. Performance testing confirmed a new 
Postgres query plan only scanning a single sub-partition when explicitely supplying _date_, at a negligible cost for the additional subquery.

![only one sub-partition scanned with date]( {{ '/assets/images/wdqms-sub-partitions-with-date.png' | relative_url }}  ){: .center-image width="25%"}
*With date information only one partition needs to be queried.*


{% highlight sql %}
SELECT station_id, nr_received, nr_expected, var_id, s.in_oscar, s.geom, country_id, rwc
                        FROM (SELECT station_id, nr_received, nr_expected, var_id
                        FROM wdqmsapi_synopobservationbysixhourperiod 
                        WHERE period_id IN ( {str_periodids} )
                        AND (var_id={param_var_id} OR ({param_var_id}=110 and var_id in (110,1)) )
                        AND (nr_received > 0 OR nr_expected > 0)
                        AND quality_only is false) o INNER JOIN wdqmsapi_synopstation s
                        ON o.station_id = s.id
{% endhighlight %}
*Original time-series query*

{% highlight sql mark_lines="6 6" %}
SELECT .. 
                        WHERE period_id IN ( {str_periodids} ) 
                        AND (var_id={param_var_id} OR ({param_var_id}=110 and var_id in (110,1)) )
                        AND (nr_received > 0 OR nr_expected > 0)
                        AND quality_only is false
                        AND date = (SELECT date FROM wdqmsapi_sixhourperiod WHERE id IN ( {str_periodids} ) LIMIT 1)
                        ) o 
		..
{% endhighlight %}

*The improved time-series query explicitely supplied date information allowing the query planner to identify the right partition. (shortened for brevity)*

#### Tile query optimization for sub-partitioning (2/2)

During testing of the new schema a performance issue was identified in the tile-server queries. The root cause was an incorrect estimation of the expected number of rows
for a tile coming from the synopstations table.

{% highlight sql %}
WHERE ST_Intersects(geom, (SELECT ST_MakeEnvelope(xmin, ymin, xmax, ymax, 3857)
{% endhighlight %}

This led to a sub-optimal query execution plan with slow response time. While this issue is already
present in the current schema, it did not affect the query planning. The reason for the incorrect estimation is that only generic statistics
are collected for select clauses only using ST_Intersects(..) on the geometry column. In the event, prefixing the query and inlining the ST_Intersects(..) call
makes the statistics collector compile more accurate statistics based on the real geospatial distribution of the data, in turn leading to more accurate 
estimation of rows by the query planner and significantly faster query execution plans, with negligible impact on performance.
{% highlight sql %}
WHERE geom && ST_MakeEnvelope(xmin, ymin, xmax, ymax, 3857) AND _ST_Intersects(geom, (SELECT ST_MakeEnvelope(xmin, ymin, xmax, ymax, 3857)))
{% endhighlight %}

#### Batch insert

The fetch-data and aggregation jobs insert bulk data into the observations and aggregations tables. Input data consists of data for different variables for the same input period.
Under the current partitioning schema this already results into inserts into each of the partitions for which there are variables in the input data.
Bulk writes can be optimized (for the current and new schema), by sorting the data by variable before inserting it.

#### New indexes

The testing of time-series queries showed better performance of more compact 2-level composite indexes over 3-level ones for the most used queries,
which aggregate across _center_. Thus, the index (station_id,date,center) will be dropped at the expense of a new index (station_id, date).

Indexes on _sixhour_period_id_, _daily_period_id_ and _monthly_period_id_ on the synopobservations table could potentially removed and be replaced 
by a new _date_ index, which could support fast retrieval of observations by all three period types. Corresponding queries will have to be 
extended by an additional date clause, which is filled with the date of the period, so that the date index is leveraged in the query planning.

## Other issues

The following schema changes, while not having drastic impact on performance, will be addressed when migrating to the new database schema.

1. Using a Postgres ENUM instead of varchar(10) for the center column. This will result in less disk space used for table and indexes at the expense of slightly more complicated schema management.
2. Removing unnecessary columns from SELECT clauses in performance critical areas (time-series, tile-queries, API download)

## Migration 

Migrating to the new database schema requires re-writing tables and indexes, as Postgres does not support partitioning existing tables. To achieve the migration without system downtime,
a strategy combining pre-populating new tables with leveraging a view and triggers to re-route inserts will be employed.

In a preparatory phase, new sub-partitioned tables are created and most of the data, up to a certain marker, is copied from old tables. This is possible because WDQMS neither updates nor deletes data.
During the migration, the old tables are renamed and replaced by a view that combines data from old and new tables. A trigger re-routes inserts into old tables to the new table. 
Remaining data is moved in batches from old to new tables. Finally, views and old tables are deleted, and the new tables renamed to the original table names.

Here are the detailed steps, taken for each of the large tables.

1. Create new table based on existing table schema, but with sub-partitions and without indexes (except for primary key).
2. Change column definitions as needed.
3. Insert data from existing table into the new table up to a recent point in time as identified by a primary key value (marker). 
4. Create indexes on new table. 
5. Start a transaction.
6. Rename existing table and create a view with the same name instead which selects data up to i from the new table and data after i from the old (and renamed) table.
7. Create a trigger on the view redirecting inserts to the new table.
8. Committ the transaction.
9. Move data greater than i in batches from the old to the new table in batches, each in a new transaction.
10. Start a transaction.
11. Delete the index and rename the new table to the original table name.
12. Committ the transaction.
13. Delete the old table

Most of the heavy lifting involved in creating and populating the new schema happens during the preparatory phase (steps 1-4). 
At the outset, a primary key value of recently inserted data is identified and stored offline. This value becomes the marker separating old from new data. 
Old data is now copied from the old to the new table. Since the system keeps using the old tables during this time, the insert can be done without indexes on the new table, speeding up the process.
Indexes are created once data has been inserted at the end of the preparatory phase. Data can be safely copied because WDQMS does not update or delete data once it is inserted.

During the hot phase of the migration, a view takes the place the old table, which itself is renamed. The view consists of a UNION statement, combining data from the new table with the old table. The SELECT statement on the old table
only selects data with a primary key greater than the marker, whereas all data from the new table is selected.
At the same time, a trigger on the view redirects INSERTs to the new table.
At this point, the system runs in degraded mode, as SELECT statements effectively query two tables. 
The system continues in this mode until the remaining data (data with a primary key greater than the marker) has been copied into the new table and been removed from the old one.
This process is performed in batches of size x and continues until no more data with primary key greater than the marker is in the old table.
Since the marker was chose for a recent date, only a small amount of data needs to be moved in this phase, keeping the time the system runs in degaraded move short.
The deletion of the view and the renaming of new table to its original name conclude the hot phase.

In a cleanup step, the old table is removed, while the system already works with the new table.


### existing queries
1. update pg tileserv query to consider date 
2. table insert query to consider partitioning, (sort by var_id and recursively insert chunks?)

## other measures
Rate limiting and caching
Remove data
pg_config (random_page cost and RAM for cache)