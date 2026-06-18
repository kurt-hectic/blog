---
layout: post
title:  "Metrics and WDQMS"
date:   2025-11-20 12:06:51 +0100
categories: wqdms
tags: wdqms 
---


Metrics are widely used in monitoring systems around the world. WIS 2.0 Global Monitoring uses OpenMetrics compatible metrics exposed by Global Services to monitor system performance and health.
Building monitoring systems around metrics, allows to leverage free and well-tested OpenSource components such as the Grafana stack for handling time-series and values at scale.

So why does WDQMS not expose, or internally use metrics to exchange information with NWP centers?

This post discusses the relation between metrics and WDQMS, and how the requirements shape the current system architecture.

## WDQMS requirements

The WDQMS process makes the following requirements of observations data quality monitoring. Observations data quality must be shared in terms of availability, quality and timeiness, for comparison by globally distributed NWP centers in a standardized way.
This allows comparison of observations data quality between centers and enables to assess the actual quality of the observation without a possible bias of individual centers.

The WDQMS process further specifies that the quality monitoring 
- is done at station level, per observed variable
- is done in terms of 6-hour, daily and monthly periods, the 6-hour period corresponding to the 4-daily NWP model runs of operational NWP.
- observation quality is defined as the observation minus the model background, constituting the principal reason for an NWP center based quality monitoring, a close second being NWP roles as main users of real-time observations exchanged through WMO networks.

These requirements translate into the following system architecture.


## WDQMS high-level information exchange architecture

Under the WDMQS concept NWP centers provide information about observation data quality in terms of availability, quality and timeliness using [standardized templates](https://wmoomm.sharepoint.com/:w:/s/wmocpdb/Efi5nglnlpVGpQP4TWCTIU8BJRAOyxW87AKXfeP5nfkh9A?rtime=0HKMboRg3Ug).
The information is provided in CSV files in 6 hour intervals, corresponding to the NWP model runs. 
The dependency on the model output is due to the quality, which is defined as observation minus model background, and which is computed after the regular 6 hourly operational model run. 
As defined in the specifications, the CSV files contain one row per station, variable and observation.

![WDQMS concept]( {{ '/assets/images/WDQMS-concept.png' | relative_url }}  )
*WDQMS data-flow, from the WDQMS User Manual*


The WDQMS webtool obtains the CSV files, and then performs data-aggregation operations, the result of which are displayed in the system. The data-aggregation includes:
- matching station identifier information in the CSV files to the station catalogue (OSCAR/Surface), 
- aggregating availability, quality and timeliness by 6 hour, daily and monthly periods, and center and variable respectively. 

At times matching station information provided in CSV files to the station catalogue is non-trivial and involves a complex and dynamic algorithm.
Likewise, deciding when to aggregate a given period can be non-trival as well, for example aggregating daily periods can only be done once all required data is available.

Data is not shown in the system until the corresponding period has been aggregated.

# Metrics in WDQMS


## definition of metric
Is something that is continously calculated and updated.
NWP centers do not continously provide data, but in 6h intervals. Data is not aggregated, but information about each observation 


## data processing, station identfiers

The calculation of metrics is key and the most difficult part of a metrics based monitoring system.
