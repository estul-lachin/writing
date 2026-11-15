---
# Copy to posts/<lowercase-hyphenated-id>.md. The id becomes the address: uig.me/writing/<id>/.
# A post is published only once `date` is set.
type: note        # incident | investigation | note
title:
date:             # YYYY-MM-DD when finished; empty = draft, not published
summary:          # one line for the list and link previews
techniques: []    # ATT&CK IDs, e.g. [T1110.001, T1105] (optional)
tool:             # splunk | sentinel | wazuh (optional)
---

Write here in Markdown. Images go in media/<id>/ and are linked as:

![What the screenshot shows](media/<id>/01-name.png)

For an incident report, these sections work well:

## Summary

## Timeline

## What the attacker did (ATT&CK)

## Impact

## Indicators

## Response

## What I changed afterwards
