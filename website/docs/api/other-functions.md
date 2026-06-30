---
sidebar_position: 7
title: Other Functions
description: Utility functions — close, delete, fork, check connection, and more
---

# Other Functions

## vis.close

```python
vis.close(win=None, env=None)
```

This function closes a specific window. It takes input window id `win` and environment id `env`. Use `win` as `None` to close all windows in an environment.

```python
# Close a specific window
vis.close(win='my_plot')

# Close all windows in the current environment
vis.close()

# Close all windows in a specific environment
vis.close(env='experiment_1')
```

## vis.delete_env

```python
vis.delete_env(env)
```

This function deletes a specified env entirely. It takes env id `env` as input.

```python
vis.delete_env('old_experiment')
```

:::warning
`delete_env` deletes all data for an environment and is **IRREVERSIBLE**. Do not use unless you absolutely want to remove an environment.
:::

## vis.fork_env

```python
vis.fork_env(prev_eid, eid)
```

This function forks an environment, similar to the UI feature.

| Argument | Description |
|----------|-------------|
| `prev_eid` | Environment ID that we want to fork |
| `eid` | New Environment ID that will be created with the fork |

```python
# Create a copy of the main environment
vis.fork_env('main', 'main_backup')
```

:::note
An exception will occur if an env that doesn't exist is forked.
:::

## vis.win_exists

```python
vis.win_exists(win, env=None)
```

This function returns a bool indicating whether or not a window `win` exists on the server already. Returns `None` if something went wrong.

```python
if vis.win_exists('my_plot'):
    vis.line(Y=[new_val], X=[step], win='my_plot', update='append')
else:
    vis.line(Y=[new_val], X=[step], win='my_plot', opts=dict(title='Training'))
```

## vis.get_env_list

```python
vis.get_env_list()
```

This function returns a list of all of the environments on the server at the time of calling. It takes no arguments.

```python
envs = vis.get_env_list()
print(envs)  # ['main', 'experiment_1', 'experiment_2']
```

## vis.get_window_data

```python
vis.get_window_data(win=None, env=None)
```

This function returns the window data for the given window. Returns data for all windows in an env if `win` is `None`.

| Argument | Description |
|----------|-------------|
| `env` | Environment to search for the window in |
| `win` | Window to return data for. Set to `None` to retrieve all the windows in an environment. |

```python
# Get data from a specific window
data = vis.get_window_data(win='my_plot', env='main')

# Get all window data in an environment
all_data = vis.get_window_data(env='main')
```

## vis.check_connection

```python
vis.check_connection(timeout_seconds=0)
```

This function returns a bool indicating whether or not the server is connected. It accepts an optional argument `timeout_seconds` for a number of seconds to wait for the server to come up.

```python
# Quick check
if vis.check_connection():
    print("Server is running")

# Wait up to 5 seconds for the server
if vis.check_connection(timeout_seconds=5):
    vis.text("Connected!")
else:
    print("Server not available")
```

## vis.replay_log

```python
vis.replay_log(log_filename)
```

This function takes the contents of a visdom log and replays them to the current server to restore a state or handle any missing entries.

```python
# Replay a previously saved log
vis.replay_log('visdom_log.json')
```

:::tip
Use `log_to_filename` when creating the Visdom client to record all operations, then replay them later with `replay_log` to restore state or migrate between servers.
:::
