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
making use of the data supplied by WDQMS's API, likely sparked by AI data-mining.

![WDQMS API usage]( {{ '/assets/images/wdqms-API-usage-2026.png' | relative_url }}  )
*WDQMS API usge in June 2026. The sixhour NWP synop data is accessed at a rate of around 10 requests per second, likey due to AI processes.*

## signs of age 

While the most time critical parts of the system, the map-tiling and API downloads endpoints, kept having satisfactory performance in the range of 300ms response times, the system started showing the limits of its current database schema 
in other areas. First, the queries delivering data to the time-series plots in the pop-up started taking upwards 30 seconds at times, resulting in inaccceptable waiting time for users.
Second, system operators informed the development team of infrequent yet persistent data-processing job failures. The metrics added in the observability release showed that these failures are related to data-loading processing exceeding the maximum allowed pod runtime of kubernetes,
during times of high database load.

Another key consideration was the desire to improve overall data-management, such as  backup, restore and archiving, which were taking several days to complete for complete table exports.

## current database schema and data-processing architecture

WDQMS uses PostgreSQL, currently in version 13, together with PostGIS spatial extensions, as database. 
Observations provided by NWP centers are matched to the station table (linked to OSCAR/Surface), but otherwise stored as-is in an observation table per observation type, and then aggregated by custom Python logic into six-hour, daily and monthly periods.
The result of the aggeregation is materialized in dedicated tables for six-hour, daily and monthly aggregations by data-processing jobs. 
Data and aggregation status for a particular aggregation-type, period and center is referenced via a *period* model. 

For example, the *SixHourPeriod* for file-type=SYNOP, center=JMA and date='2020-02-23:18:00:00+00' references data for the 18h 2020-02-23 period of SYNOP data from JMA. 
The id of the period model is a foreign key in the aggegation tables, allowing fast access to the data to the tile-server to which 
the period_id is supplied by the frontend. This design allows the database to use a single index to access the most performance critical data, 
and can also be used to remove data consistently from the databsae by deleting periods which triggers consistent and cascading data removal from aggregation tables.


![WDQMS database schema synopsixhourperiod]( {{ '/assets/images/wdqms-synopobservationsbysixhourperiod-schema-cropped.png' | relative_url }}  ){: .center-image width="50%"}
*ERD of the synopsixhour aggegation table. Aggregated observations have a foreign key on the corresponding station and period. Note the varchar(10) type for center.*

Large tables (observation and aggregation tables for the SYNOP, GBON-SYNOP and Marine types) are partitioned by var_id.

The schema of two databases tables is described in detail below. 
These tables are representative of the other large tables with other observation types and aggegations.

### the synopobservationsbysixhour table as an example of an aggregation table

The aggregation tables are indexed to support three main functions. 
First, an index on (period_id) to generate tiles for the map. The map client passes the period_id as a parameter to the map layer being shown.
Second, an index on (date) to download data from the API. A date, variable and center parameters are passed to the API by the user.  
Third, the an index on (station_id,date,center) to provide time series data to the station popup.

![WDQMS database synopsixhourperiod indices]( {{ '/assets/images/wdqms-sixhoursynopobservations-indices.png' | relative_url }}  ){: .center-image width="50%"}
*Indices of the sixhour aggegation table. Index for primary key not shown. Note the non-descriptive index names dating to an early Django version.*

![WDQMS databse schema synopsixhourperiod]( {{ '/assets/images/wdqms-synopobservations-schema-cropped.png' | relative_url }}  ){: .center-image width="50%"}
*ERD of the synop sixhour observation table.*

### the synopobservations table as an example of a raw obsevations table

The observations tables have an index for each the sixhour, daily and monthly periods, 
as well as an index on (station_id,date,center). The latter is used to provide time-series data to the six-hour quality station popup,
whereas the former are used to to obtain raw observations during the aggregations by sixhour, daily or monthly periods.

![WDQMS database synopsixhourperiod indices]( {{ '/assets/images/wdqms-synopobservation-indices.png' | relative_url }}  ){: .center-image width="50%"}
*Indices of the synop observations aggegation table. Index for primary key not shown. Note the non-descriptive index names dating to an early Django version.*


## analysis 

This section analyzes the current system behaviour in terms of data-processing cron-job failures, overall datamanagement and time-series endpoint performance. 

### data-processing failures

Both fetch-data and data aggregation jobs process multiple files or periods in a single invocation, depending on availability and readiness of data. Jobs are implemented as Kubernetes cron-jobs each running in a separate pod.
If a large number of files or periods respectively are processed at a time of high database load, the maximum pod execution time is reached and the pod terminated by the cluster.

Metrics tracking the runtime of synop observations fetch data job, show that they take between 30-180 minutes to complete. Similarly, the synop aggregation jobs take between 20-120 minutes to complete. 
The maxmium runtime is consistent with the 3h and respective 2h maximum runtime setting in the k8s configuration for fetch data and aggregation cron-jobs.

Database insertion time into the synop observations table ranges between a 10-200 records per second, with the average towards the lower (slower) end. The sixhour synop observations table has a similar pattern.

![WDQMS database insertion time]( {{ '/assets/images/wdqms-synopobservations-insertion-time.png' | relative_url }}  ){: .center-image width="50%"}
*Insertion time into synopobservations table per NWP file together with records inserted per second.*


The **reason for the data-processing failures** is therefore clearly a combination of **slow database inserts** and **numerious files or periods to process** in a single invocation. 

There are two obvious solutions to addressing the data-processing failures. One is to increase the maximum allowed processing time, the other one is to speed up database inserts.
The former is not a solution, as the system is nearing a point where data inflow exceeds the database insertion capacity. The 4 NWP centers produce 4 daily SYNOP files, which take on average 1h to insert.
This means 16 out of 24 hours are already spent inserting data.
Therefore the solution must be to speed up database inserts.

A performance experiment confirmed that index maintenance is responsible for slowliness of bulk inserts. When creating a fully partitioned but empty copy of the sixhour syop observations table and subsquently filling it 
in batches of 7000 records with the original table (having ~2.5b records), the insert performance went from an inital 400 records/second to a 20 records/second after around 20% of records inserted. Without additional indexes 
(only keeping the one for the primary key) the insert speed increased to 45000 records/second.

### data-management

The current partitioning schema by variable divides the data roughly equally and has the advantage of fast access for performance critical queries, but each partition keeps growing as time passes. This makes creating or restoring a backup difficult, as all partitions need to be 
exported for a complete backup. Under a date based partitioning schema, only the latest partition would have to be backuped. This is because WDQMS does not update or delete observations or aggregations once they are inserted into the database.
The current partitioning schema also does not allow to archive old data easily, or potentially move older and less frequently accessed data to slower/cheaper storage media.

### time-series queries

Time series queries deliver data to the popup window of individual stations and show the last 30 days of aggregated availability or timeliness in a time-series chart. In the case of six-hour quality with a center selected, the timeseries chart plots the actual quality of the observations, requiring a query of the actual observations table.


![WDQMS availability timeseries of Ghardaia station]( {{ '/assets/images/wdqms-ghardaia-all-centers.png' | relative_url }}  ){: .center-image width="50%"}
*availability timeseries of Ghardaia station.*

For the time-series, the nr_expected, nr_received, center and date attributes are needed, whereas for the quality the avg_bg_dep, date and center and for timeliness the timeliness and ng_negative_timeliness values are shown.
Selection of data is done by date range, list of station ids (station ids of the same station vary over time) and by center (in case of a timeseries for an single center view).

In support of these queries there is a composite index on (station_id, date, center) on the sixhoursynopobservations table. The first and the second level of this index are queries by range, 
as station_id is a list (typically ranging from 1-5 entries) and date is a range (of currently 30 days). The last element of the composite index is only used if a time-series for an individual center is requested.

Query planner statistics produced with EXPLAIN (ANALYZE, COSTS, BUFFERS, VERBOSE) show a planning time of ~250ms and overall execution time of 10000ms, with 500 blocks (~4MB) read, of which only 3 were cached and 497 had to be fetched from disk for 480 rows (4 centers x 4 files x 30 days).
The execution plan shows that the planner correctly identifies the relevant partition and uses the composite index.

SELECT  	"wdqmsapi_synopobservationbysixhourperiod"."id",  	"wdqmsapi_synopobservationbysixhourperiod"."var_id",  	"wdqmsapi_synopobservationbysixhourperiod"."avg_bg_dep",  	"wdqmsapi_synopobservationbysixhourperiod"."date",  	"wdqmsapi_synopobservationbysixhourperiod"."center",  	"wdqmsapi_synopobservationbysixhourperiod"."nr_expected",  	"wdqmsapi_synopobservationbysixhourperiod"."nr_received"   FROM "wdqmsapi_synopobservationbysixhourperiod"  	WHERE ("wdqmsapi_synopobservationbysixhourperiod"."date" >= '2025-07-27 21:40:10.853449440+00:00'::timestamptz  	AND "wdqmsapi_synopobservationbysixhourperiod"."date" <= '2025-08-26 21:40:10.853449440+00:00'::timestamptz  	AND "wdqmsapi_synopobservationbysixhourperiod"."station_id" IN (14198,56150,47198,35860)  	AND "wdqmsapi_synopobservationbysixhourperiod"."var_id" IN (58)); 


All in all, both fetch-data and aggregation processes 
While most jobs finish below the critical 180 minute mark after which Kubernetes terminates a pod, jobs do fail with a RuntimeExceeded error at a 
rate of slightly below once peer day.
In depth analysis of the data-loading, processing and data-writing 
    


## proposed new schema

## migration 

## other measures
Rate limiting and caching
Remove data