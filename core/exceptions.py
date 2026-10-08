from rest_framework.views import exception_handler


def _first_message(data) -> str | None:
    if isinstance(data, str):
        return data
    if isinstance(data, list) and data:
        return _first_message(data[0])
    if isinstance(data, dict):
        if 'detail' in data:
            return _first_message(data['detail'])
        for key, value in data.items():
            message = _first_message(value)
            if message:
                return message if key == 'non_field_errors' else f'{key}: {message}'
    return None


def api_exception_handler(exc, context):
    """Standard DRF errors plus a top-level `message` the frontend can toast directly."""
    response = exception_handler(exc, context)
    if response is not None:
        data = response.data if isinstance(response.data, dict) else {'errors': response.data}
        data.setdefault('message', _first_message(response.data) or 'Request failed.')
        response.data = data
    return response
