"""环境语言：2×2 因果实验的第二个因子。

**动因**（见 DEVIATIONS.md D8 与论文 §4.4）：E2 主矩阵只操纵了**用户模拟器**的语言，
而智能体读到的其余一切——系统提示（τ-bench 零售策略文档）、工具说明、工具返回的
错误串——始终是英文。于是中文臂实际上是一个**非对称混语上下文**：智能体从用户处
读中文，从环境处读英文。现有数据无法区分"中文输入"与"混语上下文"哪个是肇因。

本模块提供第二个因子：把**环境侧**的文本也换成中文，从而构造 2×2：

             环境 en                环境 zh
    用户 en   E2 主矩阵（基线）      用户说英文、环境说中文
    用户 zh   E2 主矩阵（中文臂）    **全中文**

四格之差即可分离"用户语言"与"环境语言"。

**操纵边界（必须写进论文的效度说明）：**
- **翻译**：智能体系统提示（策略文档）、16 条工具说明、全部工具**错误串**。
- **不翻译**：工具返回的**数据库内容**——用户名（`Yara Silva`）、地址（`116 Laurel
  Lane`）、订单号（`#W0661059`）、商品名（`Laptop`）。这些是**数据**，不是提示；
  翻译它们会改变任务本身。故本因子操纵的是"指令与反馈的语言"，不是"数据的语言"。
- **枚举字面量保持英文**：工具契约要求逐字传入的值（取消原因 `'no longer needed'` /
  `'ordered by mistake'`、订单状态 `pending` / `delivered` 等）在译文里**保留英文原文**
  并加中文释义。若把它们汉化，工具调用会因参数不合法而失败——那会把"语言效应"
  污染成"参数校验效应"。

**恒等保证**：`env_lang="en"` 时本模块的每个函数都**直接返回输入对象**，不做任何
变换。E2 主矩阵的可比性由此在构造上成立，而不是靠人工核对。
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List

# ── 智能体系统提示：τ-bench 零售策略文档的逐节逐条翻译 ──────────────────────
# 条款数（32 条）、章节数（8 节）、顺序、语气强度与英文原文一一对应。
# 引号内的枚举值与状态名保持英文，理由见模块 docstring。
WIKI_ZH = """# 零售客服策略

作为零售客服，你可以帮助用户取消或修改待处理订单、退货或换货已送达订单、修改其默认收货地址，或者提供与其本人资料、订单及相关商品有关的信息。

- 对话开始时，你必须通过邮箱、或通过姓名 + 邮编定位用户 id，以此完成用户身份校验。即使用户已经主动提供了 user id，这一步也必须做。

- 用户通过身份校验之后，你可以向用户提供订单、商品、资料等信息，例如帮用户查询 order id。

- 一次对话只能服务一位用户（但可以处理同一位用户的多个请求），对于任何与其他用户相关的请求都必须拒绝。

- 在采取会更新数据库的实质性操作（取消、修改、退货、换货）之前，你必须列出操作细节并取得用户明确确认（yes）后才能继续。

- 你不得编造任何未经用户或工具提供的信息、知识或流程，也不得给出主观推荐或评论。

- 你一次最多只能发起一次工具调用；如果发起了工具调用，就不得同时回复用户。如果回复了用户，就不得发起工具调用。

- 只有当请求超出你的操作范围、无法处理时，才应当把用户转接给人工客服。

## 领域基础

- 数据库中的所有时间均为 EST（美国东部时间）且为 24 小时制。例如 "02:30:00" 表示 EST 凌晨 2:30。

- 每位用户有一份资料，含邮箱、默认地址、user id 与支付方式。每种支付方式要么是礼品卡（gift card）、要么是 paypal 账户、要么是信用卡。

- 本零售店有 50 种商品类型。每种商品类型下有不同选项的变体商品。例如 't shirt' 这种商品下，可能有一件选项为 'color blue size M' 的商品，另一件选项为 'color red size L'。

- 每种商品有唯一的 product id，每件商品有唯一的 item id。两者没有关联，不得混淆。

- 每个订单的状态可以是 'pending'、'processed'、'delivered' 或 'cancelled'。一般而言，你只能对 pending 或 delivered 的订单采取操作。

- 换货或修改订单类工具只能调用一次。发起工具调用之前，务必先把所有要变更的商品收集成一个列表！！！

## 取消待处理订单

- 只有当订单状态为 'pending' 时才能取消，采取操作前你应检查其状态。

- 用户需要确认订单号以及取消原因（要么是 'no longer needed'（不再需要），要么是 'ordered by mistake'（误下单））。

- 用户确认后，订单状态将变为 'cancelled'，款项若为礼品卡支付则立即按原支付方式退回，否则需 5 到 7 个工作日。

## 修改待处理订单

- 只有当订单状态为 'pending' 时才能修改，采取操作前你应检查其状态。

- 对于待处理订单，你可以修改其收货地址、支付方式或商品选项，除此之外不能做别的。

### 修改支付方式

- 用户只能选择单一的一种、且与原支付方式不同的支付方式。

- 如果用户想把支付方式改为礼品卡，该礼品卡余额必须足以覆盖订单总额。

- 用户确认后，订单状态保持 'pending'。原支付方式若为礼品卡则立即退款，否则需 5 到 7 个工作日。

### 修改商品

- 此操作只能调用一次，调用后订单状态将变为 'pending (items modifed)'，此后客服将无法再修改或取消该订单。因此务必在操作前确认所有细节无误，并格外谨慎。特别地，记得提醒顾客确认其已提供全部需要修改的商品。

- 对于待处理订单，每件商品可以换成同一商品下、选项不同的可用新商品。不得改变商品类型，例如不得把衬衫改成鞋。

- 用户必须提供一种支付方式，用于支付或接收差价退款。如果用户提供的是礼品卡，其余额必须足以覆盖差价。

## 已送达订单退货

- 只有当订单状态为 'delivered' 时才能退货，采取操作前你应检查其状态。

- 用户需要确认订单号、要退货的商品列表，以及用于接收退款的支付方式。

- 退款必须退到原支付方式，或一张已存在的礼品卡。

- 用户确认后，订单状态将变为 'return requested'，用户会收到一封关于如何退回商品的邮件。

## 已送达订单换货

- 只有当订单状态为 'delivered' 时才能换货，采取操作前你应检查其状态。特别地，记得提醒顾客确认其已提供全部需要换货的商品。

- 对于已送达订单，每件商品可以换成同一商品下、选项不同的可用新商品。不得改变商品类型，例如不得把衬衫改成鞋。

- 用户必须提供一种支付方式，用于支付或接收差价退款。如果用户提供的是礼品卡，其余额必须足以覆盖差价。

- 用户确认后，订单状态将变为 'exchange requested'，用户会收到一封关于如何退回商品的邮件。无需下新订单。
"""

# ── 工具说明：按工具名 → 中文描述 ─────────────────────────────────────────
TOOL_DESC_ZH = {
    "calculate": "计算一个数学表达式的结果。",
    "cancel_pending_order": "取消一个待处理订单。如果订单已受理或已送达，则无法取消。客服需要说明取消细节并请用户明确确认（yes/no）后才能继续。用户确认后，订单状态将变为 'cancelled'，款项将被退回。若原支付方式为礼品卡，退款立即计入该用户的礼品卡余额；否则退款需 5–7 个工作日处理。该函数返回取消后的订单详情。",
    "exchange_delivered_order_items": "把已送达订单中的商品换成同一商品类型下的新商品。对于已送达订单，退货或换货由客服操作、且只能做一次。客服需要说明换货细节并请用户明确确认（yes/no）后才能继续。",
    "find_user_id_by_email": "通过邮箱查找 user id。如果查不到该用户，函数将返回一条错误信息。",
    "find_user_id_by_name_zip": "通过名、姓与邮编查找 user id。如果查不到该用户，函数将返回一条错误信息。默认应通过邮箱查找，只有在用邮箱查不到、或用户不记得邮箱时才调用本函数。",
    "get_order_details": "获取某个订单的状态与详情。",
    "get_product_details": "获取某个商品的库存详情。",
    "get_user_details": "获取某位用户的详情，包括其订单。",
    "list_all_product_types": "列出全部商品类型的名称与 product id。每种商品类型下有若干件 item id 与选项各不相同的商品。本店只有 50 种商品类型。",
    "modify_pending_order_address": "修改待处理订单的收货地址。客服需要说明修改细节并请用户明确确认（yes/no）后才能继续。",
    "modify_pending_order_items": "把待处理订单中的商品换成同一商品类型下的新商品。对于待处理订单，本函数只能调用一次。客服需要说明换货细节并请用户明确确认（yes/no）后才能继续。",
    "modify_pending_order_payment": "修改待处理订单的支付方式。客服需要说明修改细节并请用户明确确认（yes/no）后才能继续。",
    "modify_user_address": "修改某位用户的默认地址。客服需要说明修改细节并请用户明确确认（yes/no）后才能继续。",
    "return_delivered_order_items": "退回已送达订单中的部分商品。订单状态将变为 'return requested'。客服需要说明退货细节并请用户明确确认（yes/no）后才能继续。用户将收到后续邮件，说明如何退回以及退到哪里。",
    "think": "用这个工具进行思考。它不会获取新信息、也不会改变数据库，只会把该思考追加到日志中。需要进行复杂推理或需要一些缓存记忆时使用。",
    "transfer_to_human_agents": "把用户转接给人工客服，并附上用户问题的摘要。只有当用户明确要求人工客服、或用户的问题无法用现有工具解决时才转接。",
}

# ── 工具参数说明：(工具名, 参数名) → 中文 ─────────────────────────────────
_PARAM_ORDER_ID = "订单号，形如 '#W0000000'。注意订单号开头有一个 '#' 符号。"
_PARAM_PM_ID = "用于支付或接收差价的支付方式 id，形如 'gift_card_0000000' 或 'credit_card_0000000'。这些可以从用户或订单详情中查到。"
_PARAM_ITEM_IDS = "要操作的 item id 列表，每个形如 '1008292230'。列表中可能存在重复项。"
_PARAM_NEW_ITEM_IDS = "要换成的 item id 列表，每个形如 '1008292230'。列表中可能存在重复项。每个新 item id 应与同一位置上的原 item id 对应，且属于同一商品。"
_PARAM_ADDR = {
    "address1": "地址第一行，形如 '123 Main St'。",
    "address2": "地址第二行，形如 'Apt 1' 或 ''。",
    "city": "城市，形如 'San Francisco'。",
    "state": "州，形如 'CA'。",
    "country": "国家，形如 'USA'。",
    "zip": "邮编，形如 '12345'。",
}
TOOL_PARAM_DESC_ZH = {
    ("calculate", "expression"): "要计算的数学表达式，例如 '2 + 2'。表达式中可含数字、运算符（+、-、*、/）、括号与空格。",
    ("cancel_pending_order", "order_id"): _PARAM_ORDER_ID,
    ("cancel_pending_order", "reason"): "取消原因，应为 'no longer needed'（不再需要）或 'ordered by mistake'（误下单）之一。",
    ("find_user_id_by_email", "email"): "用户邮箱，形如 'something@example.com'。",
    ("find_user_id_by_name_zip", "first_name"): "顾客的名，形如 'John'。",
    ("find_user_id_by_name_zip", "last_name"): "顾客的姓，形如 'Doe'。",
    ("find_user_id_by_name_zip", "zip"): "顾客的邮编，形如 '12345'。",
    ("get_order_details", "order_id"): _PARAM_ORDER_ID,
    ("get_product_details", "product_id"): "product id，形如 '6086499569'。注意 product id 与 item id 不同。",
    ("get_user_details", "user_id"): "user id，形如 'sara_doe_496'。",
    ("think", "thought"): "要思考的内容。",
    ("transfer_to_human_agents", "summary"): "用户问题的摘要。",
}
for _t in ("exchange_delivered_order_items", "modify_pending_order_items",
           "return_delivered_order_items"):
    TOOL_PARAM_DESC_ZH[(_t, "order_id")] = _PARAM_ORDER_ID
    TOOL_PARAM_DESC_ZH[(_t, "item_ids")] = _PARAM_ITEM_IDS
    TOOL_PARAM_DESC_ZH[(_t, "payment_method_id")] = _PARAM_PM_ID
for _t in ("exchange_delivered_order_items", "modify_pending_order_items"):
    TOOL_PARAM_DESC_ZH[(_t, "new_item_ids")] = _PARAM_NEW_ITEM_IDS
TOOL_PARAM_DESC_ZH[("modify_pending_order_payment", "order_id")] = _PARAM_ORDER_ID
TOOL_PARAM_DESC_ZH[("modify_pending_order_payment", "payment_method_id")] = _PARAM_PM_ID
for _t in ("modify_pending_order_address", "modify_user_address"):
    for _k, _v in _PARAM_ADDR.items():
        TOOL_PARAM_DESC_ZH[(_t, _k)] = _v
TOOL_PARAM_DESC_ZH[("modify_pending_order_address", "order_id")] = _PARAM_ORDER_ID
TOOL_PARAM_DESC_ZH[("modify_user_address", "user_id")] = "user id，形如 'sara_doe_496'。"

# ── 工具错误串：τ-bench 零售环境返回的全部 16 条 ───────────────────────────
OBS_ZH = {
    "Error: insufficient gift card balance to pay for the new item": "错误：礼品卡余额不足以支付新商品的费用",
    "Error: insufficient gift card balance to pay for the order": "错误：礼品卡余额不足以支付该订单",
    "Error: invalid characters in expression": "错误：表达式含非法字符",
    "Error: invalid reason": "错误：取消原因不合法",
    "Error: non-delivered order cannot be exchanged": "错误：非已送达订单不能换货",
    "Error: non-delivered order cannot be returned": "错误：非已送达订单不能退货",
    "Error: non-pending order cannot be cancelled": "错误：非待处理订单不能取消",
    "Error: non-pending order cannot be modified": "错误：非待处理订单不能修改",
    "Error: order not found": "错误：未找到该订单",
    "Error: payment method not found": "错误：未找到该支付方式",
    "Error: payment method should be either the original payment method or a gift card": "错误：支付方式必须要么是原支付方式，要么是一张礼品卡",
    "Error: product not found": "错误：未找到该商品",
    "Error: some item not found": "错误：部分商品未找到",
    "Error: the number of items to be exchanged should match": "错误：要换货的商品数量应当一致",
    "Error: there should be exactly one payment for a pending order": "错误：待处理订单应当恰好有一笔支付",
    "Error: insufficient gift card balance to pay for the price difference":
        "错误：礼品卡余额不足以支付差价",
    "Error: the new payment method should be different from the current one":
        "错误：新的支付方式必须与当前支付方式不同",
    "Error: user not found": "错误：未找到该用户",
}

# ── 长度配平附录（仅 `zhp` 臂使用）────────────────────────────────────────
# 中文政策文档与工具说明比英文短约 7.6%（首轮 prompt 少约 336 token）。为了把
# 「环境语言」与「提示长度」分开，`zhp` 臂在中文系统提示之后追加下面这段**语义冗余**
# 的术语对照附录：它不新增任何策略规则，只把上文出现过的工具名与枚举取值再列一遍，
# 并在开头显式声明「与上文冲突时以上文为准」。长度按实测首轮 prompt 校准（见
# `scripts/calibrate_pad.py`）。
WIKI_ZH_PAD = """

## 附录 A：工具与取值对照表

仅为检索对照，不含任何新规则；与正文冲突时以正文为准。

工具：`calculate` 做四则运算；`cancel_pending_order` 取消待处理订单；
`exchange_delivered_order_items` 已送达订单换货；`find_user_id_by_email` 按邮箱查用户
id；`find_user_id_by_name_zip` 按姓名与邮编查用户 id；`get_order_details` 读订单详情；
`get_product_details` 读商品详情；`get_user_details` 读用户资料；`list_all_product_types`
列出商品类别；`modify_pending_order_address` 改待处理订单收货地址；
`modify_pending_order_items` 待处理订单换货；`modify_pending_order_payment` 改待处理
订单支付方式；`modify_user_address` 改用户地址；`return_delivered_order_items` 已送达
订单退货；`think` 内部思考一步；`transfer_to_human_agents` 转人工客服。

取值：订单状态有 `pending` 待处理、`processed` 已处理、`delivered` 已送达、`cancelled`
已取消四种；取消订单的原因只有 `no longer needed` 不再需要与 `ordered by mistake`
下错单两种；支付方式分为礼品卡、`paypal` 账户与信用卡三类。
"""


LANGS = ("en", "zh")
# 另一个可选臂 `zhp`：中文环境 + 上面那段术语对照附录，把系统提示长度补回英文环境
# 的水平。它只用于**长度配平对照**（排除环境语言这一维附带的 −7.6% 提示长度混杂），
# 不属于主因子。见 DEVIATIONS D9。
ENV_LANGS = ("en", "zh", "zhp")


def _base(lang: str) -> str:
    """把 zhp 归约到它所继承的基础语言（zh），其余原样。"""
    return "zh" if lang == "zhp" else lang


# ── 第二类反馈：框架层的「调用参数不合法」错误 ──────────────────────────────
# `env.step` 把工具调用抛出的异常包成 `f"Error: {e}"`。除上表 16 条环境自撰的
# 错误外，还有一类由 pydantic 生成——智能体**自己**把工具调得不对（漏参、参数名写错），
# 于是校验失败。主矩阵 4,320 格中这类共 96 次，占全部工具报错的 3.4%，形态只有两种。
#
# **是否翻译**：翻译。它是智能体**自身动作的反馈**，属于本因子操纵的"反馈语言"；
# 若留着英文，中文环境臂就仍留一条英文反馈通道，与主矩阵的中文臂同病。
# **保留什么**：工具名（`Think`）、方法名（`.invoke()`）、参数名（`'thought'`）一律原样——
# 它们是标识符，指代必须精确；只翻"缺少 N 个必需的位置参数"这类框语句。
_RE_MISSING = re.compile(
    r"^Error: (?P<tool>[\w.]+)\.invoke\(\) missing (?P<n>\d+) "
    r"required positional argument(?:s)?: (?P<args>.+)$"
)
_RE_UNEXPECTED = re.compile(
    r"^Error: (?P<tool>[\w.]+)\.invoke\(\) got an unexpected keyword argument (?P<arg>.+)$"
)
# 第三类：环境自撰、但把标识符嵌进句子的错误串（无法整串精确匹配）。2026-10-08 的
# 2×2 批次审计发现 OBS_ZH 漏了这一条：env=zh 的 1,080 格里 10 格残留英文原文
# （0.93%），形态是 `Error: new item <product_id> not found or available`。
# 商品 id 是数据，原样保留；只翻框语句。
_RE_NEW_ITEM = re.compile(r"^Error: new item (?P<pid>[\w-]+) not found or available$")
# 第四类：`modify_pending_order_items` / `exchange_delivered_order_items` 里的
# `f"Error: {item_id} not found"`（订单或商品 id 直接嵌进句子）。**必须排在精确表
# 之后**：`user not found` / `order not found` 等已在 OBS_ZH 中精确命中，形态更具体的
# 正则只用于兜住带 id 的那一种。
_RE_ID_NOT_FOUND = re.compile(r"^Error: (?P<oid>[\w-]+) not found$")

# 不翻译的一类：`tau_bench/envs/base.py` 的兜底 `f"Error: {e}"`，它把任意异常的
# 原文直接拼进来，没有可翻译的固定框语句。5,400 格（E2 主矩阵 + 2×2 两批）中
# 一次也没出现过；作为已知残余写在这里，由门禁显式豁免而不是装作不存在。
_GENERIC_WRAPPER = re.compile(r"^Error: .+$")     # 仅用于门禁豁免的标记，不参与翻译


def _translate_pydantic(text: str) -> str | None:
    """翻第二至四类带变量的错误串；不匹配任何已知形态时返回 None（由调用方原样返回）。"""
    m = _RE_MISSING.match(text)
    if m:
        return (f"错误：{m['tool']}.invoke() 缺少 {m['n']} 个必需的位置参数：{m['args']}")
    m = _RE_UNEXPECTED.match(text)
    if m:
        return f"错误：{m['tool']}.invoke() 收到意外的关键字参数 {m['arg']}"
    m = _RE_NEW_ITEM.match(text)
    if m:
        return f"错误：新商品 {m['pid']} 未找到或不可用"
    m = _RE_ID_NOT_FOUND.match(text)
    if m and text not in OBS_ZH:
        return f"错误：未找到 {m['oid']}"
    return None


def wiki(lang: str) -> str:
    """智能体系统提示。en 直接回原文档；zh 回逐条译文；zhp 再追加长度配平附录。"""
    if lang == "en":
        from tau_bench.envs.retail.wiki import WIKI
        return WIKI
    if lang == "zh":
        return WIKI_ZH
    if lang == "zhp":
        return WIKI_ZH + WIKI_ZH_PAD
    raise ValueError(f"未知环境语言：{lang!r}（只支持 {ENV_LANGS}）")


def tools_info(tools_info: List[Dict[str, Any]], lang: str) -> List[Dict[str, Any]]:
    """翻译工具说明。en 恒等返回**原对象**；zh / zhp 深拷贝后替换，不污染 env.tools_info。

    缺失任何一条翻译即报错——静默回退会造成两臂指令不一致，是效度事故。
    """
    if lang == "en":
        return tools_info
    if _base(lang) != "zh":
        raise ValueError(f"未知环境语言：{lang!r}（只支持 {ENV_LANGS}）")

    out = copy.deepcopy(tools_info)
    for t in out:
        fn = t["function"]
        name = fn["name"]
        if name not in TOOL_DESC_ZH:
            raise KeyError(f"工具 {name!r} 缺少中文说明，拒绝静默回退到英文。")
        fn["description"] = TOOL_DESC_ZH[name]
        for pname, pval in (fn.get("parameters", {}).get("properties") or {}).items():
            key = (name, pname)
            if key not in TOOL_PARAM_DESC_ZH:
                raise KeyError(f"工具参数 {name}.{pname} 缺少中文说明，拒绝静默回退到英文。")
            if isinstance(pval, dict) and "description" in pval:
                pval["description"] = TOOL_PARAM_DESC_ZH[key]
    return out


def observation(text: str, lang: str) -> str:
    """翻译智能体**看到**的反馈串。en 恒等；zh 翻两类错误串，其余原样返回。

    翻译对象只有两类，都做整串精确匹配、不做子串替换：
      1. 环境自撰的 16 条错误串（`OBS_ZH`，已与 vendor 源码逐条核对）；
      2. 框架层的调用参数错误（`_translate_pydantic`，两种形态）。
    数据库内容（订单/商品/用户的 JSON）、用户发言、`###STOP###` 控制标记一律原样——
    它们是数据与控制协议，不是环境在"说话"。

    **未覆盖的错误串原样返回而非报错**：长跑中若出现未预见的框架消息，宁可留下一串
    英文并在事后审计中发现，也不能让它把整格打崩。zh 格的审计口径很直接——
    **翻译后的中文错误串不再以 `Error:` 开头**，故事后扫 transcript 数一遍仍以
    `Error:` 开头的工具观察，即为漏翻条数（见 `scripts/verify_env_lang.py` 与
    `scripts/analyze_2x2.py`）。
    """
    if lang == "en":
        return text
    if _base(lang) != "zh":
        raise ValueError(f"未知环境语言：{lang!r}（只支持 {ENV_LANGS}）")
    if text in OBS_ZH:
        return OBS_ZH[text]
    return _translate_pydantic(text) or text


def fingerprint(lang: str) -> str:
    """环境语言操纵的实现指纹，落进 summary.json 供事后校验。

    覆盖本模块真正参与操纵的三类文本（系统提示、工具说明与参数说明、错误串映射）。
    两臂必然不同；若同批内出现指纹漂移，说明该批的环境侧文本被改过。
    """
    import hashlib
    import json

    if lang == "en":
        wiki_text = wiki("en")
        payload = {
            "wiki": wiki_text,
            "tool_desc": {"__en__": "tau-bench 原文，未经本模块改写"},
            "param_desc": {},
            "obs": {"__en__": "原样透传"},
        }
    elif lang in ("zh", "zhp"):
        payload = {
            "wiki": WIKI_ZH if lang == "zh" else WIKI_ZH + WIKI_ZH_PAD,
            "tool_desc": TOOL_DESC_ZH,
            "param_desc": {f"{k[0]}.{k[1]}": v for k, v in TOOL_PARAM_DESC_ZH.items()},
            "obs": OBS_ZH,
        }
    else:
        raise ValueError(f"未知环境语言：{lang!r}（只支持 {ENV_LANGS}）")
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]
