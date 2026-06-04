import urllib
import tempfile
import os.path
import numpy as np
import json


def misc_plot_matplot(viz, env, args):
    try:
        import matplotlib.pyplot as plt
        plt.plot([1, 23, 2, 4])
        plt.ylabel('some numbers')
        viz.matplot(plt, env=env)
    except BaseException as err:
        print('Skipped matplotlib example')
        print('Error message: ', err)

# Example for Latex Support
def misc_plot_latex(viz, env, args):
    return viz.line(
        X=[1, 2, 3, 4],
        Y=[1, 4, 9, 16],
        name=r'$\alpha_{1c} = 352 \pm 11 \text{ km s}^{-1}$',
        opts={
            'showlegend': True,
            'title': "Demo Latex in Visdom",
            'xlabel': r'$\sqrt{(n_\text{c}(t|{T_\text{early}}))}$',
            'ylabel': r'$d, r \text{ (solar radius)}$',
        },
        env=env
    )

def misc_plot_latex_update(viz, env, args):
    win = misc_plot_latex(viz, env, args)
    viz.line(
        X=[1, 2, 3, 4],
        Y=[0.5, 2, 4.5, 8],
        win=win,
        name=r'$\beta_{1c} = 25 \pm 11 \text{ km s}^{-1}$',
        update='append',
        env=env
    )


def misc_video_tensor(viz, env, args):
    try:
        video = np.empty([256, 250, 250, 3], dtype=np.uint8)
        for n in range(256):
            video[n, :, :, :].fill(n)
        viz.video(tensor=video, env=env)
    except BaseException as e:
        print('Skipped video tensor example.' + str(e))


def misc_video_download(viz, env, args):
    try:
        # video demo:
        # download video from http://media.w3.org/2010/05/sintel/trailer.ogv
        video_url = 'http://media.w3.org/2010/05/sintel/trailer.ogv'
        videofile = os.path.join(tempfile.gettempdir(), 'trailer.ogv')
        urllib.request.urlretrieve(video_url, videofile)

        if os.path.isfile(videofile):
            viz.video(videofile=videofile, opts={'width': 864, 'height': 480}, env=env)
    except BaseException as e:
        print('Skipped video file example', e)


# audio demo:
def misc_audio_basic(viz, env, args):
    tensor = np.random.uniform(-1, 1, 441000)
    viz.audio(tensor=tensor, opts={'sample_frequency': 441000}, env=env)

# audio demo:
# download from http://www.externalharddrive.com/waves/animal/dolphin.wav
def misc_audio_download(viz, env, args):
    try:
        audio_url = 'http://www.externalharddrive.com/waves/animal/dolphin.wav'
        audiofile = os.path.join(tempfile.gettempdir(), 'dolphin.wav')
        urllib.request.urlretrieve(audio_url, audiofile)

        if os.path.isfile(audiofile):
            viz.audio(audiofile=audiofile, env=env)
    except BaseException:
        print('Skipped audio example')
 
# Arbitrary visdom content
def misc_arbitrary_visdom(viz, env, args):
    trace = dict(x=[1, 2, 3], y=[4, 5, 6], mode="markers+lines", type='custom',
                 marker={'color': 'red', 'symbol': 104, 'size': "10"},
                 text=["one", "two", "three"], name='1st Trace')
    layout = dict(title="First Plot", xaxis={'title': 'x1'},
                  yaxis={'title': 'x2'})

    viz._send({'data': [trace], 'layout': layout, 'win': 'mywin', 'eid': env})

# get/set state
def misc_getset_state(viz, env, args):
    window = viz.text('test one', env=env)
    data = json.loads(viz.get_window_data(window, env=env))
    data['content'] = 'test two'
    viz.set_window_data(json.dumps(data), env=env, win=window)


