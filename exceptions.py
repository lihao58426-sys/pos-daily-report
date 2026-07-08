"""
自定义异常类
===========
职责：为不同的失败场景定义明确的异常类型，替代裸 except Exception。

为什么不用裸 except Exception？
  - 网络断了 → 应该重试
  - 密码错了 → 不应该重试（重试也没用）
  - 数据格式变了 → 应该告警
  三种失败需要三种不同的处理方式，但 except Exception 把它们混在一起。

用法：
  raise AuthError("登录失败，账号或密码错误")
  raise ParseError(f"解析商品排名失败: {e}")
  raise PushError(f"企微推送失败: {e}")
"""


class AuthError(Exception):
    """认证/登录失败

    场景：银豹后台登录失败（密码错误、验证码、账号被锁等）
    处理：不应重试，需人工介入检查账号密码
    """
    pass


class ParseError(Exception):
    """数据解析失败

    场景：页面结构变化导致原有选择器匹配不到数据、HTML 格式变了等
    处理：记录原始 HTML 到调试文件，告警通知开发者
    """
    pass


class PushError(Exception):
    """消息推送失败

    场景：企微 Webhook 不可达、网络不通、响应异常等
    处理：可重试（网络问题），或切换备用渠道
    """
    pass


class ConfigError(Exception):
    """配置错误

    场景：配置文件缺失、环境变量未设置、格式错误等
    处理：立刻终止，提示用户检查配置
    """
    pass
