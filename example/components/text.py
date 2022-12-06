
def text_basic(viz, env, args):
    title = None if args is None or len(args) == 0 else args[0]
    return viz.text('Hello World!', env=env, opts={'title': title})

def text_update(viz, env, args):
    updatetextwindow = viz.text('Hello World! More text should be here', env=env)
    assert updatetextwindow is not None, 'Window was none'
    viz.text('And here it is', win=updatetextwindow, append=True, env=env)

def text_callbacks(viz, env, args):
    # text window with Callbacks
    txt = 'This is a write demo notepad. Type below. Delete clears text:<br>'
    callback_text_window = viz.text(txt, env=env)

    def type_callback(event):
        if event['event_type'] == 'KeyPress':
            curr_txt = event['pane_data']['content']
            if event['key'] == 'Enter':
                curr_txt += '<br>'
            elif event['key'] == 'Backspace':
                curr_txt = curr_txt[:-1]
            elif event['key'] == 'Delete':
                curr_txt = txt
            elif len(event['key']) == 1:
                curr_txt += event['key']
            viz.text(curr_txt, win=callback_text_window, env=env)

    viz.register_event_handler(type_callback, callback_text_window)
    return callback_text_window

# close text window:
def text_close(viz, env, args):
    textwindow = text_basic(viz, env, args)
    viz.close(win=textwindow, env=env)

    # assert that the closed window doesn't exist
    assert not viz.win_exists(textwindow), 'Closed window still exists'


# helpers for forking test
def text_fork_part1(viz, env, args):
    viz.text('This text will change. Fork to the rescue!', env=env, win="fork_test")
def text_fork_part2(viz, env, args):
    viz.text('Changed text.', env=env, win="fork_test")


