---
# Drafted with Claude from my own Splunk searches and results (lessons 2–3, 2026-11-15).
type: investigation
title: One script, 64 sources — an IoT botnet that marks its victims "PBOC"
date: 2026-11-15
tool: splunk
incident:
techniques: [T1110.001, T1078.001, T1059.004, T1027, T1057, T1083, T1082]
summary: From one repeat visitor to a 64-source IoT botnet and a sample of its default-password dictionary
playbooks: []
---

## Alert

No alert fired. This started as a detection idea: find sources that **fail a few logins and then
succeed** (`cowrie.login.failed` before `cowrie.login.success`), on `index=honeypot_demo` from
2026-11-08 to 2026-11-15.

Before analysing, I checked the data. My first searches returned nothing past 2026-11-12 because
`./hp pull` had not run since; after refreshing, I made sure nothing was indexed twice:

```spl
index=honeypot_demo sourcetype=cowrie:json
| stats count AS events dc(_raw) AS unique_events min(_time) AS first max(_time) AS last
| convert ctime(first) ctime(last)
```

![34,088 events, 34,088 unique, 2026-11-08 to 2026-11-15](media/pboc-iot-botnet/01-data-quality.png)

Then the two login outcomes:

![52 failed logins, 1,165 successful](media/pboc-iot-botnet/02-login-counts.png)

52 failures against 1,165 successes. Cowrie accepts most passwords by design, so on a honeypot a
successful login is not a compromise; on a production host the same ratio would be critical.

```spl
index=honeypot_demo sourcetype=cowrie:json eventid IN ("cowrie.login.failed","cowrie.login.success")
| stats count(eval(eventid="cowrie.login.failed")) AS failed
        count(eval(eventid="cowrie.login.success")) AS success
        min(eval(if(eventid="cowrie.login.failed",_time,null()))) AS first_fail
        min(eval(if(eventid="cowrie.login.success",_time,null()))) AS first_success
        by src_ip
| where failed>=1 AND success>=1 AND first_fail<first_success
| convert ctime(first_fail) ctime(first_success)
| sort - failed
```

![7 sources, each failing at most twice before getting in](media/pboc-iot-botnet/03-fail-then-success.png)

Seven sources matched, and none was a real brute force: each failed at most twice and got in
0.2–9 seconds later. A `failed >= 10` threshold would never fire on this data. One source,
`src-ec7f9e57`, stood out: 2 failures, 29 successful logins, 55 connections.

## Scope

**What `src-ec7f9e57` did.** 150 commands across its sessions, 107 of which Cowrie did not emulate,
over Telnet as well as SSH. All 150 were the same six commands, repeated each session:

```spl
index=honeypot_demo sourcetype=cowrie:json src_ip="src-ec7f9e57" eventid="cowrie.command.input"
| stats count by input
| sort - count
```

![enable, system, linuxshell, shell, sh, /bin/busybox UNSTABLE](media/pboc-iot-botnet/04-ec7f9e57-commands.png)

`enable`, `system`, `linuxshell` and `shell` are the "escape to a Linux shell" commands of several
vendors' device CLIs; `/bin/busybox UNSTABLE` checks for a real BusyBox shell. That is a typical
opening for an IoT bot. No file download followed.

**Pivot on the behaviour.** Every command starting with `/bin/busybox`:

```spl
index=honeypot_demo sourcetype=cowrie:json eventid="cowrie.command.input" input="/bin/busybox*"
| stats count dc(src_ip) AS sources by input
| sort - sources
```

![487 distinct BusyBox commands; one block seen 66 times from 64 sources](media/pboc-iot-botnet/05-busybox-variants.png)

- `/bin/busybox` with no argument: 2,054 times from 138 sources, generic probing.
- A block of commands each seen **66 times from the same 64 sources**: one script, many infected hosts.
  It writes a shell script `.k` in hex chunks with `echo -ne`. Decoded, it starts with a loop over
  `/proc/*` that reads each `/proc/$pid/exe`, consistent with finding and killing competing malware.
  It then tests directories for a writable and executable location
  (`echo > /tmp/.b && sh /tmp/.b && cd /tmp/`, the same for `/dev/shm`, `/var/run`, `/mnt` and others),
  and runs **`/bin/busybox hostname PBOC`**, renaming the device as a marker.

**Credentials.** A subsearch on the 64 sources that ran `hostname PBOC`:

```spl
index=honeypot_demo sourcetype=cowrie:json eventid="cowrie.login.success"
    [ search index=honeypot_demo sourcetype=cowrie:json input="/bin/busybox hostname PBOC"
      | dedup src_ip | fields src_ip ]
| stats dc(src_ip) AS sources count by username password
| sort - sources
```

![66 logins, 50 distinct username/password pairs](media/pboc-iot-botnet/06-pboc-credentials.png)

66 logins, 50 distinct pairs, mostly what look like device defaults (`root/hkipc2016`,
`e8ehome/e8ehome`, `Alphanetworks/wrgn49_dlob_dir600b`) plus generic ones (`root/000000`,
`admin/1234`). Because Cowrie accepts the first password it does not reject, each source logged in
once with a different pair: the 50 pairs are a **sample of the botnet's dictionary**, not passwords
it "knew".

## Timeline

| UTC | Event |
|---|---|
| 2026-11-08 17:00:32 | `src-ec7f9e57` first failed login; first success 1 s later |
| 2026-11-08 to 11-15 | 64 sources run the `hostname PBOC` script, 66 sessions in total |
| 2026-11-15 06:38 | last event in the refreshed data |

## ATT&CK mapping

| Technique | Evidence |
|---|---|
| T1110.001 Password Guessing | short dictionary attempts before each login |
| T1078.001 Default Accounts | dictionary of IoT device default credentials |
| T1059.004 Unix Shell | `sh`, `/bin/busybox …` |
| T1027 Obfuscated Files or Information | script written as hex with `echo -ne` |
| T1057 Process Discovery | `.k` loops over `/proc/*/exe` |
| T1083 File and Directory Discovery | probing directories for write and execute |
| T1082 System Information Discovery | BusyBox environment check |

## Verdict

Automated, untargeted IoT botnet activity with Mirai-style behaviour. 64 sources running an
identical script point to infected devices spreading the bot, not a single operator. On a honeypot
this is expected and has no impact.

## Response

On a real network the same pattern would mean: block and investigate the sources; look for a
`PBOC` hostname and the `.k` and `.b` files on exposed devices; change every factory-default
password; close Telnet and SSH to the internet where they are not needed. The 50 credential pairs
are an IOC list for auditing my own devices.

## What I would do differently

- Start from the data, not the threshold: "many failures, then success" barely exists on a honeypot
  that accepts most passwords, so pivoting on behaviour (commands) found far more than the login rule.
- Check freshness first: check the index time range and duplicates before analysing, not after an
  empty result.
