import numpy as np

# image demo
def image_basic(viz, env):
    img_callback_win = viz.image(
        np.random.rand(3, 512, 256),
        opts={'title': 'Random!', 'caption': 'Click me!'},
    )
    return img_callback_win

def image_callback(viz, env):
    img_callback_win = image_basic(viz, env)
    img_coord_text = viz.text("Coords: ")

    def img_click_callback(event):
        nonlocal img_coord_text
        if event['event_type'] != 'Click':
            return

        coords = "x: {}, y: {};".format(
            event['image_coord']['x'], event['image_coord']['y']
        )
        img_coord_text = viz.text(coords, win=img_coord_text, append=True)

    viz.register_event_handler(img_click_callback, img_callback_win)

# image demo save as jpg
def image_save_jpeg(viz, env):
    viz.image(
        np.random.rand(3, 512, 256),
        opts=dict(title='Random image as jpg!', caption='How random as jpg.', jpgquality=50),
    )

# image history demo
def image_history(viz, env):
    viz.image(
        np.random.rand(3, 512, 256),
        win='image_history',
        opts=dict(caption='First random', store_history=True, title='Pick your random!'),
    )
    viz.image(
        np.random.rand(3, 512, 256),
        win='image_history',
        opts=dict(caption='Second random!', store_history=True),
    )

# grid of images
def image_grid(viz, env):
    viz.images(
        np.random.randn(20, 3, 64, 64),
        opts=dict(title='Random images', caption='How random.')
    )

# SVG plotting
def image_svg(viz, env):
    svgstr = """
    <svg height="300" width="300">
      <ellipse cx="80" cy="80" rx="50" ry="30"
       style="fill:red;stroke:purple;stroke-width:2" />
      Sorry, your browser does not support inline SVG.
    </svg>
    """
    viz.svg(
        svgstr=svgstr,
        opts=dict(title='Example of SVG Rendering')
    )


