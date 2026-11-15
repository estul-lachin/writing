---
type: investigation
title: 'Alert, then login: triaging a correlation hit that turned out to be a window artifact'
date: '2026-11-15'
summary: Reproducing the scan-then-login playbook, explaining Wazuh's missing row, and disproving my own "4 hours of recon" finding
techniques: [T1595, T1110, T1078]
tool: splunk
playbooks: [scan-then-login]
---

## Alert

The [scan-then-login](../../playbooks/scan-then-login/) playbook joins two sensors on the source
address: Suricata (network) and Cowrie (shell session). It lists sources whose **first Suricata alert
came before their first successful login**, the shape of "reconnaissance, then intrusion".

Over all data (2026-11-08 to 2026-11-15) it returned 46 sources:

![46 sources with an alert before their first login](media/alert-then-login-triage/01-alert-then-login-all.png)

## Scope

**Reproducing the verified result.** The playbook was verified on 2026-11-11 (UTC): 10 rows in
Splunk and Sentinel, 9 in Wazuh. I pinned the same day inside the search, so the time picker
cannot change the result, and added the gap between alert and login in milliseconds:

```spl
index=honeypot_demo earliest="11/11/2026:00:00:00" latest="11/12/2026:00:00:00" (sourcetype=suricata:alert) OR (sourcetype=cowrie:json eventid="cowrie.login.success")
| stats count(eval(sourcetype="suricata:alert")) AS alerts
        count(eval(sourcetype="cowrie:json")) AS logins
        min(eval(if(sourcetype="suricata:alert", _time, null()))) AS first_alert
        min(eval(if(sourcetype="cowrie:json", _time, null()))) AS first_login
        by src_ip
| where alerts > 0 AND logins > 0 AND first_alert < first_login
| eval gap_sec=round(first_login-first_alert, 3)
| eval first_alert=strftime(first_alert, "%F %T.%3N"), first_login=strftime(first_login, "%F %T.%3N")
| sort gap_sec
```

![10 rows on 2026-11-11, sorted by the gap between alert and login](media/alert-then-login-triage/02-reproduce-2026-11-11.png)

Exactly 10 rows, matching the stored verification. Three things stood out:

- **Wazuh's missing row is `src-d1334c03`.** Both times read `16:25:15.632` even at millisecond
  precision; the alert is less than a millisecond earlier. Splunk keeps microseconds, so `<` holds;
  Wazuh keeps milliseconds, both events land on the same instant and the row drops out. `<=` would
  bring it back, but would also count events that really are simultaneous.
- **8 of the 10 rows have a gap under 2 seconds.** Those alerts are most likely raised by the login
  connection itself: one action seen by two sensors, not reconnaissance followed by an intrusion.
- **Two rows looked like real reconnaissance:** `src-4c20ec41` (2 minutes) and `src-4c400ccd`
  (18 alerts, first login 4 h 10 min later). I triaged the stronger one.

**Triage of `src-4c400ccd`: what were the alerts?**

```spl
index=honeypot_demo sourcetype=suricata:alert src_ip="src-4c400ccd"
| fillnull value="(none)" app_proto
| stats count min(_time) AS first max(_time) AS last by signature dest_port app_proto
| sort first
| convert ctime(first) ctime(last)
```

My first version returned nothing: `stats … by` drops any event missing one of the by-fields, and
none of this source's alerts had an `app_proto`. `fillnull` fixed it.

![One signature, 129 times, port 22](media/alert-then-login-triage/03-4c400ccd-signatures.png)

All 129 alerts are one informational rule, `ET INFO SSH-2.0-Go version string Observed in Network
Traffic`, on port 22, from 11-09 to 11-15: a Go SSH client connecting again and again. Not a scan,
not an exploit.

**When did it first appear in each sensor?**

```spl
index=honeypot_demo src_ip="src-4c400ccd"
| stats count min(_time) AS first max(_time) AS last by sourcetype
| convert ctime(first) ctime(last)
```

![Cowrie sees it on 11-08, Suricata only from 11-09](media/alert-then-login-triage/04-4c400ccd-first-seen.png)

It was in Cowrie on **2026-11-08 19:51**, nearly a day before its first Suricata alert, and it had
already logged in and run commands that day.

## Timeline

| UTC | Event |
|---|---|
| 2026-11-08 19:51:49 | `src-4c400ccd` first connects to Cowrie and logs in (no Suricata data exists yet) |
| 2026-11-09 18:48:02 | its first Suricata alert: `ET INFO SSH-2.0-Go version string` |
| 2026-11-11 00:33:38 | first alert inside the verification day |
| 2026-11-11 04:44:09 | first login inside the verification day: the "4 h 10 min" gap |
| 2026-11-15 05:36:37 | last activity in the data |

## ATT&CK mapping

| Technique | Evidence |
|---|---|
| T1595 Active Scanning | what the playbook looks for; **not** supported for this source |
| T1110 Brute Force | repeated automated SSH logins from a Go client |
| T1078 Valid Accounts | logins accepted by the honeypot |

## Verdict

False positive for "reconnaissance, then intrusion". The 4-hour gap was an artifact of the analysis
window, for two reasons:

1. **Window truncation:** limited to 2026-11-11, `min(_time)` only saw that day's first login, not
   the one on 11-08. The earlier alerts that day were its own unsuccessful connections.
2. **Different sensor coverage:** in the pseudonymized data Cowrie starts on 11-08 and Suricata on
   11-09. Nothing on 11-08 can ever look like "alert first".

The source is an automated Go-based SSH tool logging in repeatedly over a week. The playbook result
is a list of candidates, not a finding.

## Response

None needed on a honeypot. On a real network: block the source and treat the Go SSH client string
as a low-confidence signal to combine with failed-login volume, not as an alert on its own.

## What I would do differently

- After a correlation hit, read the signature and its level (`INFO`, `SCAN`, `EXPLOIT`) before
  counting alerts.
- Widen the time range to find where a source **first** appears before calling anything a sequence.
- Check each data source's start and end dates: a period one sensor did not cover cannot prove order.
- When `stats … by` loses rows, suspect a missing by-field first.
