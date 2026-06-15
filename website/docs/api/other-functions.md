---
sidebar_position: 7
title: Other Functions
description: Utility functions — close, delete, fork, check connection, and more
---

# Other Functions

## vis.close

This function closes a specific window. It takes input window id `win` and environment id `eid`. Use `win` as `None` to close all windows in an environment.

## vis.delete_env

This function deletes a specified env entirely. It takes env id `eid` as input.

:::warning
`delete_env` deletes all data for an environment and is **IRREVERSIBLE**. Do not use unless you absolutely want to remove an environment.
:::

## vis.fork_env

This function forks an environment, similar to the UI feature.

**Arguments:**
- `prev_eid`: Environment ID that we want to fork
- `eid`: New Environment ID that will be created with the fork

:::note
An exception will occur if an env that doesn't exist is forked.
:::

## vis.win_exists

This function returns a bool indicating whether or not a window `win` exists on the server already. Returns `None` if something went wrong.

**Optional arguments:**
- `env`: Environment to search for the window in. Default is `None`.

## vis.get_env_list

This function returns a list of all of the environments on the server at the time of calling. It takes no arguments.

## vis.get_window_data

This function returns the window data for the given window. Returns data for all windows in an env if `win` is `None`.

**Arguments:**
- `env`: Environment to search for the window in
- `win`: Window to return data for. Set to `None` to retrieve all the windows in an environment.

## vis.check_connection

This function returns a bool indicating whether or not the server is connected. It accepts an optional argument `timeout_seconds` for a number of seconds to wait for the server to come up.

## vis.replay_log

This function takes the contents of a visdom log and replays them to the current server to restore a state or handle any missing entries.

**Arguments:**
- `log_filename`: log file to replay the contents of
