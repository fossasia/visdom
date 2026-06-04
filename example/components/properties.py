from components.text import text_callbacks

# Properties window
def properties_basic(viz, env, args):
    properties = [
        {'type': 'text', 'name': 'Text input', 'value': 'initial'},
        {'type': 'number', 'name': 'Number input', 'value': '12'},
        {'type': 'button', 'name': 'Button', 'value': 'Start'},
        {'type': 'checkbox', 'name': 'Checkbox', 'value': True},
        {'type': 'select', 'name': 'Select', 'value': 1, 'values': ['Red', 'Green', 'Blue']},
    ]
    properties_window = viz.properties(properties, env=env)
    return properties, properties_window


def properties_callbacks(viz, env, args):
    callback_text_window = text_callbacks(viz, env, args)
    properties, properties_window = properties_basic(viz, env, args)

    def properties_callback(event):
        if event['event_type'] == 'PropertyUpdate':
            prop_id = event['propertyId']
            value = event['value']
            if prop_id == 0:
                new_value = value + '_updated'
            elif prop_id == 1:
                new_value = value + '0'
            elif prop_id == 2:
                new_value = 'Stop' if properties[prop_id]['value'] == 'Start' else 'Start'
            else:
                new_value = value
            properties[prop_id]['value'] = new_value
            viz.properties(properties, win=properties_window, env=env)
            viz.text("Updated: {} => {}".format(properties[event['propertyId']]['name'], str(event['value'])),
                     win=callback_text_window, append=True, env=env)

    viz.register_event_handler(properties_callback, properties_window)
