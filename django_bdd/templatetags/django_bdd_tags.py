from django import template

# used for registering custom template tags
register = template.Library()


@register.filter(name='access')
def access(value, key):
    """Gets a specified key out of a specified collection."""
    # if the collection is a list and the key is an index, make sure we don't go out of bounds
    if isinstance(value, list):
        key %= len(value)
    return value[key]


@register.simple_tag(takes_context=True)
def url_search_parameter_update(context, key, value):
    """Inspects the current url parameters with the context of a web request,
    and updates them based on the key and value passed in so that the return
    value of this method can be used as a url in tags.html or similar links.
    """
    request = context['request']
    params = request.GET.copy()

    # pull the specified url parameter key out of the dict
    if key in params:
        old_value = params[key]
        values = old_value.split('+')  # search items are separated by +

        # if the value is not in the old value, add it
        if value not in values:
            values.append(value)
        else:
            # the value is already there, remove it
            values.remove(value)

        # now put the values back into the 'key' field of the url parameters
        params[key] = '+'.join(values)

        # delete the parameter if it has no values
        if not params[key]:
            del params[key]
    else:
        # it's a new parameter, just set it equal to value
        params[key] = value

    return params.urlencode()
