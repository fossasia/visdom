import numpy as np

# image demo
def image_basic(viz, env, args):
    img_callback_win = viz.image(
        np.random.rand(3, 512, 256),
        opts={'title': 'Random!', 'caption': 'Click me!'},
        env=env
    )
    return img_callback_win

def image_callback(viz, env, args):
    img_callback_win = image_basic(viz, env, args)
    img_coord_text = viz.text("Coords: ", env=env)

    def img_click_callback(event):
        nonlocal img_coord_text
        if event['event_type'] != 'Click':
            return

        coords = "x: {}, y: {};".format(
            event['image_coord']['x'], event['image_coord']['y']
        )
        img_coord_text = viz.text(coords, win=img_coord_text, append=True, env=env)

    viz.register_event_handler(img_click_callback, img_callback_win)

# image callback demo
image_color = 0
def image_callback2(viz, env, args):
    def show_color_image_window(color, win=None):
        image = np.full([3, 256, 256], color, dtype=float)
        return viz.image(
            image,
            opts=dict(title='Colors', caption='Press arrows to alter color.'),
            win=win,
            env=env
        )

    callback_image_window = show_color_image_window(image_color)

    def image_callback(event):
        global image_color
        if event['event_type'] == 'KeyPress':
            if event['key'] == 'ArrowRight':
                image_color = min(image_color + 0.2, 1)
            if event['key'] == 'ArrowLeft':
                image_color = max(image_color - 0.2, 0)
            show_color_image_window(image_color, callback_image_window)

    viz.register_event_handler(image_callback, callback_image_window)

# image demo save as jpg
def image_save_jpeg(viz, env, args):
    viz.image(
        np.random.rand(3, 512, 256),
        opts=dict(title='Random image as jpg!', caption='How random as jpg.', jpgquality=50),
        env=env
    )

# image history demo
def image_history(viz, env, args):
    viz.image(
        np.random.rand(3, 512, 256),
        win='image_history',
        opts=dict(caption='First random', store_history=True, title='Pick your random!'),
        env=env
    )
    viz.image(
        np.random.rand(3, 512, 256),
        win='image_history',
        opts=dict(caption='Second random!', store_history=True),
        env=env
    )

# grid of images
def image_grid(viz, env, args):
    viz.images(
        np.random.randn(20, 3, 64, 64),
        opts=dict(title='Random images', caption='How random.'),
        env=env
    )

# SVG plotting
def image_svg(viz, env, args):
    svgstr = """
    <svg height="300" width="300">
      <ellipse cx="80" cy="80" rx="50" ry="30"
       style="fill:red;stroke:purple;stroke-width:2" />
      Sorry, your browser does not support inline SVG.
    </svg>
    """
    viz.svg(
        svgstr=svgstr,
        opts=dict(title='Example of SVG Rendering'),
        env=env
    )


