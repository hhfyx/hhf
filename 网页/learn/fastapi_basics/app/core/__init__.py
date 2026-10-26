# -*- coding: utf-8 -*-
"""core：横切关注点 —— 配置、依赖、错误、中间件。

import 顺序上 core 不依赖 api / schemas（services 只被 core.deps 弱引用），
所以这里可以放心地被任何层 import。
"""
