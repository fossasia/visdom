
def text_basic(viz, env):
    return viz.text('Hello World!')

def text_update(viz, env):
    updatetextwindow = viz.text('Hello World! More text should be here')
    assert updatetextwindow is not None, 'Window was none'
    viz.text('And here it is', win=updatetextwindow, append=True)

def text_callbacks(viz, env):
    # text window with Callbacks
    txt = 'This is a write demo notepad. Type below. Delete clears text:<br>'
    callback_text_window = viz.text(txt)

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
            viz.text(curr_txt, win=callback_text_window)

    viz.register_event_handler(type_callback, callback_text_window)

# close text window:
def text_close(viz, env):
    textwindow = text_basic(viz, env)
    viz.close(win=textwindow)

    # assert that the closed window doesn't exist
    assert not viz.win_exists(textwindow), 'Closed window still exists'


