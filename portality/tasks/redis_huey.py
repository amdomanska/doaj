from huey import RedisHuey, crontab
from portality.core import app

main_queue = RedisHuey('doaj', host=app.config['HUEY_REDIS_HOST'], port=app.config['HUEY_REDIS_PORT'], always_eager=app.config.get("HUEY_EAGER", False))

def schedule(action):
    cfg = app.config.get("HUEY_SCHEDULE", {})
    action_cfg = cfg.get(action)
    if action_cfg is None:
        raise RuntimeError(u"No configuration for scheduled action '{x}'.  Define this in HUEY_SCHEDULE first then try again.".format(x=action))

    month = action_cfg.get("month", "*")
    day = action_cfg.get("day", "*")
    hour = action_cfg.get("hour", "*")
    minute = action_cfg.get("minute", "*")
    return crontab(month=month, day=day, hour=hour, minute=minute)

def configure(action):
    cfg = app.config.get("HUEY_TASKS", {})
    action_cfg = cfg.get(action)
    if action_cfg is None:
        raise RuntimeError(u"No task configuration for action '{x}'.  Define this in HUEY_TASKS first then try again.".format(x=action))
    return action_cfg

