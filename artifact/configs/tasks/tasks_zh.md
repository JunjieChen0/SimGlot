# E1 中文任务套件（人工复核稿）

- 任务数：**30**（与 `data/task_sample.json` 的抽样集一一对应）
- **操纵的变量**：仅用户侧语言——模拟用户读中文指令、说中文
- **保持不变的**：智能体的系统提示词、工具定义、数据库全部沿用 τ-bench 英文原样
- **逐字保留**：姓名、邮箱、订单号、邮编、金额、商品变体 ID、技术规格
- **译成自然中文**：商品名、选项值、城市州名、人设与情绪词、条件决策树、行为约束

> 这样设计使中英两臂唯一的差别是「客户说什么语言」，从而能把分数差异归因到语言本身。
> 商品名与选项值被译成中文，智能体必须自己跨语言对上英文目录——这正是本审计要测的能力。

> ✅ 自动校验 A–E 全部通过（不变项保全、覆盖完整、无游离英文硬错误、数字保全、长度合理）。

## 歧义清单（逐条记录）

共 **18/30** 条存在需要在预跑中观察的歧义：

| 任务 | 意图族 | 复杂度 | 歧义点 |
|---|---|---|---|
| #5 | items | 4-5 | 「AC」在原文指交流电源适配器；译作「交流电」是否足以让智能体对上商品选项，需在预跑中确认。 |
| #14 | items | 6+ | 原文未点明具体商品，要求模拟用户自己把握「哪些算游戏相关」；中文版保留同一开放度。 |
| #15 | items | 6+ | 「want the material」原文有歧义（想知道材质，还是指定材质）；中文照留歧义，不替模拟用户做决定。 |
| #19 | items | 6+ | 原文「Mention the two things together」指把退水壶与换货合并提出；中文用「一起说」对应。 |
| #23 | items | 6+ | 「the grill you just ordered」与「the one you already received」需要智能体自己找出两笔订单；中文保留同样的指代模糊性。 |
| #24 | none | 0-1 | 「which two t-shirts you have ordered」中文用「那两件」保持定指，不点明订单号。 |
| #26 | transfer | 6+ | 真值要求退到信用卡不可行时转人工（真值动作含 transfer_to_human_agents），但原文未说明退款方式偏好，需由模拟用户即兴提出；中文版保留同一开放度，不补写 amex。 |
| #28 | items | 6+ | 「cancel the hose you just ordered」与前面要退的「garden hose」是否为同一件，原文未澄清；中文照留歧义。 |
| #41 | items+address | 6+ | 「possibly correct all order addresses and your user address」中的「可能」是模糊限定；中文用「可能的话」保留。 |
| #43 | address | 4-5 | 「check if the storage of the tablet you ordered」原文缺谓语，语义为「确认容量」；中文按此理解，记为轻微歧义。 |
| #59 | cancel | 6+ | 「the older order」需模拟用户自己判断哪笔更早；中文未点明，保留检索负担。 |
| #72 | items+address | 2-3 | 原文「you do not want to mention it, but it is in your user profile」要求模拟用户刻意隐瞒地址；中文保留该约束。 |
| #74 | cancel | 2-3 | 「五件商品」是检索线索而非订单号，模拟用户不会给出订单号；中文保留。 |
| #78 | cancel | 2-3 | 结构化规格里未给出的字段（如套装规格）应保持原值不变；中文未额外说明，与原英文一致。 |
| #91 | items | 2-3 | 「If the same item is available online, you're willing to exchange」适用对象（滑板还是阅读器）原文不明确；中文照留歧义。 |
| #95 | items | 0-1 | 「8GB」与「32GB」指向不同规格维度（内存 / 已购机型），中文未加解释，保留原文的辨识难度。 |
| #105 | items+address | 4-5 | 原文用「cancel these two things」而真值动作是退货（return）；中文译作「取消」，与原文的措辞不一致问题一并保留。 |
| #108 | items | 2-3 | 「more fancy theme」无客观标准，需模拟用户自己把握；中文保留同一开放度。 |

## 逐条对照

### #5　items／4-5

**英文原指令**

> You are mei_kovacs_8020 (zip code 28236) and you want to exchange the water bottle and the desk lamp. You want to exchange the water bottle to a bigger one, and the desk lamp to a less bright one (prefer battery > USB > AC). If the agent asks for confirmation, only exchange the desk lamp. If the agent asks for confirmation again, do not exchange anything, and return the water bottle instead.

**中文指令**

> 你是 mei_kovacs_8020（邮编 28236），你想把水瓶和台灯都换掉。水瓶换成更大号的，台灯换成亮度更低的（优先电池 > USB > 交流电）。如果客服让你确认，那就只换台灯。如果客服再让你确认一次，那就什么都别换，改成把水瓶退掉。

*逐字保留项*：`mei_kovacs_8020`、`28236`、`USB`　*字符比*：0.31

*翻译取舍*：「battery > USB > AC」保留原有优先级箭头写法，仅译单位词。

*歧义记录*：「AC」在原文指交流电源适配器；译作「交流电」是否足以让智能体对上商品选项，需在预跑中确认。

---

### #9　items／6+

**英文原指令**

> You are mei_kovacs_8020 (zip code 28236) and you want to exchange the water bottle and the desk lamp. You want to exchange the water bottle to a bigger one, and the desk lamp to a brighter one (prefer AC adapter > battery > USB). If the agent asks for confirmation, only exchange the desk lamp.

**中文指令**

> 你是 mei_kovacs_8020（邮编 28236），你想把水瓶和台灯都换掉。水瓶换成更大号的，台灯换成亮度更高的（优先交流电源 > 电池 > USB）。如果客服让你确认，那就只换台灯。

*逐字保留项*：`mei_kovacs_8020`、`28236`、`USB`　*字符比*：0.32

*翻译取舍*：与 #5 是同一场景的对照变体（条件分叉不同），措辞保持平行以便配对比较。

---

### #14　items／6+

**英文原指令**

> You are mia_garcia_4516 (mia.garcia2723@example.com). You just quit gaming and want to cancel or return everything associated with it. (It's just a keyboard and a mouse, but do not reveal it to the agent). Original payment is preferred. You are into gaming but realized the importance of studying hard.

**中文指令**

> 你是 mia_garcia_4516（mia.garcia2723@example.com）。你刚戒掉游戏，想把跟游戏有关的东西全部取消或者退掉。（其实只有一个键盘和一个鼠标，但别告诉客服。）退款优先走原来的支付方式。你本来还挺喜欢打游戏的，后来想明白了还是得好好学习。

*逐字保留项*：`mia_garcia_4516`、`mia.garcia2723@example.com`　*字符比*：0.45

*翻译取舍*：「quit gaming / I'm into gaming but realized…」是带矛盾感的语气，译作「刚戒掉」+「本来还挺喜欢」保留这层张力。

*歧义记录*：原文未点明具体商品，要求模拟用户自己把握「哪些算游戏相关」；中文版保留同一开放度。

---

### #15　items／6+

**英文原指令**

> You are Fatima Johnson in 78712. You want to modify the pending boots to a size 8, and want the material, but do not care about waterproof or not. You are a private person that does not want to reveal much about yourself.

**中文指令**

> 你是 Fatima Johnson，住在 78712。你想把还没发货的那双靴子改成 8 码，材质你在意，防不防水倒无所谓。你是个不爱说自己事的人，不太想透露个人信息。

*逐字保留项*：`Fatima Johnson`、`78712`、`8`　*字符比*：0.38

*翻译取舍*：「private person」译作「不爱说自己事的人」，保留行为约束（少透露信息）。

*歧义记录*：「want the material」原文有歧义（想知道材质，还是指定材质）；中文照留歧义，不替模拟用户做决定。

---

### #17　address／6+

**英文原指令**

> You are Fatima Johnson in 78712. You want to change #W8665881 to be delivered to Suite 641 instead. You are a private person that does not want to reveal much about yourself.

**中文指令**

> 你是 Fatima Johnson，住在 78712。你想把订单 #W8665881 改成送到 Suite 641。你是个不爱说自己事的人，不太想透露个人信息。

*逐字保留项*：`Fatima Johnson`、`78712`、`#W8665881`、`Suite 641`　*字符比*：0.46

*翻译取舍*：Suite 641 是数据库里的英文地址格式，保留原样。

---

### #19　items／6+　（含输出约束）

**英文原指令**

> You are Mei Davis in 80217. You want to return the water bottle, and exchange the pet bed and office chair to the cheapest version. Mention the two things together. If you can only do one of the two things, you prefer to do whatever saves you most money, but you want to know the money you can save in both ways. You are in debt and sad today, but very brief.

**中文指令**

> 你是 Mei Davis，住在 80217。你想把水瓶退掉，并且把宠物床和办公椅都换成最便宜的版本。这两件事要一起说。如果这两件事只能办成一件，你更愿意办省钱最多的那件，但你想知道两种做法各自能省下多少钱。你现在欠着钱，今天心情很差，说话非常简短。

*逐字保留项*：`Mei Davis`、`80217`　*字符比*：0.35

*翻译取舍*：「in debt and sad today, but very brief」→ 「欠着钱、心情很差、说话非常简短」，保留情绪与话痨程度两条约束。

*歧义记录*：原文「Mention the two things together」指把退水壶与换货合并提出；中文用「一起说」对应。

---

### #23　items／6+

**英文原指令**

> You are Sofia Hernandez, and you live in Seattle, WA, 98193. You want to exchange the helmet for a medium sized, red, high ventilation type, and you want to exchange the luggage set (in another order) to a two-piece black one with soft material. Lastly, you want to modify the grill you just ordered to the same type as the one you already received.

**中文指令**

> 你是 Sofia Hernandez，住在西雅图，华盛顿州，98193。你想把头盔换成中号、红色、高透气的那种；还想把另一笔订单里的行李箱套装换成两件套、黑色、软质地的；最后，你想把刚下单的那台烤架改成和你已经收到的那台同一个型号。

*逐字保留项*：`Sofia Hernandez`、`98193`　*字符比*：0.33

*翻译取舍*：城市州名译中文（西雅图、华盛顿州）；邮编保留，因为查库靠邮编。头盔选项「medium / red / high ventilation」译作「中号、红色、高透气」。

*歧义记录*：「the grill you just ordered」与「the one you already received」需要智能体自己找出两笔订单；中文保留同样的指代模糊性。

---

### #24　none／0-1　（含输出约束）

**英文原指令**

> You are Sofia Hernandez, and you live in Seattle, WA, 98193. You want to cancel the grill, but if the agent asks you to confirm, you regret and want to keep it. You then want to ask which two t-shirts you have ordered in another order, and what materials are they. Make everything sound very natural and make up reasons.

**中文指令**

> 你是 Sofia Hernandez，住在西雅图，华盛顿州，98193。你想取消那台烤架，但如果客服让你确认，你就后悔了，想留着。然后你想问另一笔订单里你买的那两件T恤分别是什么、都是什么材质。尽量说得自然一点，随口编些理由。

*逐字保留项*：`Sofia Hernandez`、`98193`、`T恤`　*字符比*：0.35

*翻译取舍*：「Make everything sound very natural and make up reasons」是给模拟用户的行为指令，必须保留——它直接影响模拟器的即兴程度。

*歧义记录*：「which two t-shirts you have ordered」中文用「那两件」保持定指，不点明订单号。

---

### #26　transfer／6+

**英文原指令**

> You are Isabella Johansson, and you live in 32286. You have an order sent to Texas by accident, and you want to know the tracking number of the order, and return all items in it except the pet bed. You don't remember the order number. It is urgent.

**中文指令**

> 你是 Isabella Johansson，住在 32286。你有一笔订单不小心寄到得克萨斯州去了，你想知道这笔订单的快递单号，除了宠物床以外，里面的东西你都要退掉。你不记得订单号了。这件事很急。

*逐字保留项*：`Isabella Johansson`、`32286`　*字符比*：0.4

*翻译取舍*：保留「不记得订单号」这一约束——它是逼智能体去检索的关键。

*歧义记录*：真值要求退到信用卡不可行时转人工（真值动作含 transfer_to_human_agents），但原文未说明退款方式偏好，需由模拟用户即兴提出；中文版保留同一开放度，不补写 amex。

---

### #27　items／6+

**英文原指令**

> You are Isabella Johansson, and you live in 32286. You want to return the hose, backpack, and exchange the hiking boots to the exact same item except that it is waterproof. Make sure you mention the two requests at the same time, and if the agent can only do one, you prefer the exchange. You are a bit anxious and want to get things done quickly.

**中文指令**

> 你是 Isabella Johansson，住在 32286。你想退掉软管和背包，并把登山靴换成完全一样的款式、只要求防水。这两个要求一定要同时说出来；如果客服只能办一件，你更想办换货那件。你有点焦虑，想把事情快点办完。

*逐字保留项*：`Isabella Johansson`、`32286`　*字符比*：0.32

*翻译取舍*：「the exact same item except that it is waterproof」强调「除防水外完全相同」，中文保留这层限定。

---

### #28　items／6+　（含输出约束）

**英文原指令**

> You are Isabella Johansson, and you live in 32286. You want to return the skateboard, garden hose, backpack, keyboard, bed, and also cancel the hose you just ordered (if cancelling one item is not possible, forget about it, you just want to cancel the hose and nothing else). You want to know how much you can get in total as refund. You are extremely brief but patient.

**中文指令**

> 你是 Isabella Johansson，住在 32286。你想退掉滑板、花园水管、背包、键盘和床，另外还想取消你刚下单的那个水管（如果没法只取消一件商品，那就算了——反正你要取消的只有那个水管，不带别的）。你想知道总共能退回多少钱。你说话极其简短，但很有耐心。

*逐字保留项*：`Isabella Johansson`、`32286`　*字符比*：0.36

*翻译取舍*：「extremely brief but patient」两条行为约束并存，译文保留「极其简短」与「很有耐心」的矛盾搭配。

*歧义记录*：「cancel the hose you just ordered」与前面要退的「garden hose」是否为同一件，原文未澄清；中文照留歧义。

---

### #40　payment／4-5　（含输出约束）

**英文原指令**

> You are Isabella Lopez, and your email address is isabella.lopez3271@example.com. You want to know how much balance does your gift card have. Also, for your recent order, whether you used your visa, mastercard, or amex credit card. You also wonder if you can apply the gift card balance to the order. If not, you want to change your payment method to visa, because the other two cards have a lot of balance. You are a yound college student under the pressure of final exams and student loans, so you are a bit anxious and want to get things done quickly.

**中文指令**

> 你是 Isabella Lopez，邮箱是 isabella.lopez3271@example.com。你想知道你的礼品卡里还剩多少余额。另外，你最近那笔订单，你想知道用的是 visa、mastercard 还是 amex 信用卡。你还在想能不能把礼品卡的余额用到这笔订单上。如果不行，你想把支付方式改成 visa，因为另外两张卡的额度都还不少。你是个正被期末考和助学贷款压着的大学生，所以有点焦虑，想把事情快点办完。

*逐字保留项*：`Isabella Lopez`、`isabella.lopez3271@example.com`、`visa`、`mastercard`、`amex`　*字符比*：0.38

*翻译取舍*：卡组织名 visa / mastercard / amex 是数据库原值，保留拉丁写法；别名表已登记「万事达」等中文说法以免误判。

---

### #41　items+address／6+

**英文原指令**

> Your name is Mei Patel, and you live in 445 Maple Drive, Suite 394, Fort Worth, Texas, 76165. You just created your user id mei_patel_7272 and ordered some things, but you have two problems: first, the 1000-piece intermediate jigsaw might be too hard for your little kid, you wonder if you can change it to the easiest one with fewest pieces; second, you might have typed your address wrong. You want to check it, and potentially correct all order addresses and your user address. Make sure you mention these two problems at the same time in the same order. You are brief and your memory is not too good sometimes, but you are polite.

**中文指令**

> 你叫 Mei Patel，住在 445 Maple Drive, Suite 394, Fort Worth, Texas, 76165。你刚注册了账号 mei_patel_7272，下了几笔单，但现在有两个问题：第一，那幅 1000 片的进阶拼图对你家小孩来说可能太难了，你想知道能不能换成片数最少、最简单的那款；第二，你怀疑自己地址填错了。你想核对一下，并且可能的话把各笔订单的收货地址和你的账户地址都改过来。这两个问题一定要按这个顺序、同时说出来。你说话简短，记性有时不太好，但很有礼貌。

*逐字保留项*：`Mei Patel`、`445 Maple Drive`、`Suite 394`、`Fort Worth`、`Texas`、`76165`、`mei_patel_7272`、`1000`　*字符比*：0.39

*翻译取舍*：完整邮寄地址按数据库英文格式保留。

*歧义记录*：「possibly correct all order addresses and your user address」中的「可能」是模糊限定；中文用「可能的话」保留。

---

### #43　address／4-5　（含输出约束）

**英文原指令**

> You are Lucas (lucas_santos_6600), you live in Denver CO 80239, and your daughter lives in Chicago. You order some things for her but she has not received, so you want to know which address the order was sent to, the tracking number, and if the order is still in transit. You also want to check if the storage of the tablet you ordered. Lastly, you want to change your default address to your daughter's address so that you don't have to change it every time you order something for her. You are a lonely man and you want to talk to the agent for a while.

**中文指令**

> 你是 Lucas（lucas_santos_6600），住在丹佛，科罗拉多州，80239，你女儿住在芝加哥。你给她买了些东西，可她一直没收到，所以你想知道这笔订单寄到哪个地址去了、快递单号是多少、现在是不是还在运输途中。你还想确认一下你买的那台平板的存储容量。最后，你想把自己的默认地址改成你女儿的地址，这样以后给她买东西就不用每次都改。你是个有点孤单的人，想跟客服多聊一会儿。

*逐字保留项*：`Lucas`、`lucas_santos_6600`、`80239`　*字符比*：0.34

*翻译取舍*：城市州名译中文；本任务 outputs 含 'Chicago'/'IL' 等英文地址项，别名表已登记『芝加哥』『伊利诺伊州』，两臂同尺。

*歧义记录*：「check if the storage of the tablet you ordered」原文缺谓语，语义为「确认容量」；中文按此理解，记为轻微歧义。

---

### #59　cancel／6+　（含输出约束）

**英文原指令**

> You are Yusuf Taylor from San Jose, CA, 95154. You recently placed two orders, and now you would like to make several changes and checks. You'll first inquire about the status difference between your two orders, #W2702727 and #W8268610, since both are "pending," but one was placed much earlier in the year. You are considering cancelling the older order as you find the wait time unreasonable. If the agent cannot guarantee the older order will be processed within 5 days, you want to cancel it. You also want to confirm the total price of the refund.

For order #W2702727, you intend to switch the shipping address to your new home in a different city because you plan to move prior to its delivery next month. Your new address is 1234 Elm St, Springfield, IL, 62701. You want the agent to confirm the change and ensure the order will be delivered to the new address. You also want to confirm the total price of the order after the address change.

Your approach will be firm, as you are unhappy with the pending status's duration but try to make all requests in one go and ask for them to be resolved efficiently and correctly in context with each other.

**中文指令**

> 你是 Yusuf Taylor，来自圣何塞，加州，95154。你最近下了两笔订单，现在想做几处修改和核对。你会先问这两笔订单——#W2702727 和 #W8268610——的状态为什么不一样，因为它们都显示「待处理」，但其中一笔是今年早些时候下的。你在考虑取消那笔更早的订单，因为等待时间长得不合理。如果客服不能保证那笔较早的订单会在 5 天内处理完，你就想取消它。你还想确认退款总额。

对于订单 #W2702727，你打算把收货地址改到你另一个城市的新家，因为你打算在下个月收货前搬过去。新地址是 1234 Elm St, Springfield, IL, 62701。你想让客服确认这次修改，并保证订单会送到新地址。你还想确认改完地址之后这笔订单的总价。

你的态度会比较强硬，因为你对「待处理」拖这么久很不满，但你会尽量把所有要求一次性提完，并要求它们被高效、正确、并且彼此关联地一起解决。

*逐字保留项*：`Yusuf Taylor`、`95154`、`#W2702727`、`#W8268610`、`5`、`1234 Elm St`、`Springfield`、`IL`、`62701`　*字符比*：0.35

*翻译取舍*：新地址按客户会照抄的形式保留英文；「pending」译作「待处理」。三段结构与原文一致，长指令的分段对模拟用户的行为也重要。

*歧义记录*：「the older order」需模拟用户自己判断哪笔更早；中文未点明，保留检索负担。

---

### #61　items／4-5

**英文原指令**

> You are Chen Johnson from Houston TX, 77004. You want to change your wireless earbuds in order W5061109 to a blue colored one. Provide all details upfront and ask the agent to resolve as soon as possible. You want the price to be the same or lower.

**中文指令**

> 你是 Chen Johnson，来自休斯顿，得克萨斯州，77004。你想把订单 W5061109 里的无线耳机换成蓝色的。把细节一次说清楚，并要求客服尽快处理。你希望价格不比原来高。

*逐字保留项*：`Chen Johnson`、`77004`、`W5061109`　*字符比*：0.37

*翻译取舍*：原订单号未带 '#'，中文同样不带，保持与数据库书写一致。

---

### #72　items+address／2-3

**英文原指令**

> You name is Ivan Khan and your zip code is 28243. You are polite, optimistic, organized. You made some mistake and ordered an order sent to your son's address in Washington DC, and you want to modify it to your default address in Charlotte (you do not want to mention it, but it is in your user profile the agent can look up) because he is coming back home. You also want to adjust the desk lamp to be black color, and the backpack to be medium size and polyester material instead. If multiple colors are available for the backpack, you prefer grey. If the agent asks for payment method, you say GC initially, but if the agent does not allow it or asks you to confirm it, you change your mind to PayPal, and decide to only modify the backpack. Make sure you briefly mention the two things at the same time at the beginning, but first mention the modification then the address.

**中文指令**

> 你叫 Ivan Khan，邮编 28243。你有礼貌、乐观、有条理。你不小心把一笔订单寄到了你儿子在华盛顿特区的地址，你想改成你在夏洛特的默认地址（你不想主动说出这个地址，但它在你账户资料里，客服查得到），因为他快要回家了。你还想把台灯改成黑色，把背包改成中号和涤纶材质。如果背包有多种颜色可选，你更想要灰色。如果客服问支付方式，你一开始说礼品卡，但如果客服说不行、或者让你确认，你就改口说 PayPal，并且决定只改背包。开头一定要把这两件事简短地同时提一下，但先说商品修改、再说地址。

*逐字保留项*：`Ivan Khan`、`28243`、`PayPal`　*字符比*：0.28

*翻译取舍*：「GC」译作「礼品卡」（数据库里为 gift_card_*）；PayPal 保留原名。条件分叉（支付方式一变就缩减为只改背包）逐条保留。

*歧义记录*：原文「you do not want to mention it, but it is in your user profile」要求模拟用户刻意隐瞒地址；中文保留该约束。

---

### #73　items／0-1

**英文原指令**

> You name is Fatima Wilson and your email is fatima.wilson5721@example.com. You are polite, flexible, creative. You want to return everything you just bought except the coffee machine.

**中文指令**

> 你叫 Fatima Wilson，邮箱是 fatima.wilson5721@example.com。你有礼貌、随和、有创意。除了咖啡机，你刚买的东西全都想退掉。

*逐字保留项*：`Fatima Wilson`、`fatima.wilson5721@example.com`　*字符比*：0.44

*翻译取舍*：「flexible, creative」属人设词，译作「随和、有创意」以影响模拟用户的应对方式。

---

### #74　cancel／2-3

**英文原指令**

> You name is Lei Li and your zip code is 85033. You are insecure, shy. You recently bought a laptop, but you want to exchange it to i9 CPU. If multiple storage options are available, you prefer 256GB SSD. If multiple colors are available, you prefer silver. You also have a pending order with five items (you don't remember order ID), and you want to cancel it because you no longer need them.

**中文指令**

> 你叫 Lei Li，邮编 85033。你没什么安全感，怕生。你最近买了台笔记本电脑，想换成 i9 处理器的。如果有多个存储规格可选，你更想要 256GB 固态硬盘。如果有多种颜色，你更想要银色。你还有一笔待处理订单，里面有五件商品（你不记得订单号了），你想取消它，因为你不再需要了。

*逐字保留项*：`Lei Li`、`85033`、`i9`、`256GB`　*字符比*：0.36

*翻译取舍*：「i9」「256GB SSD」为数据库规格原值，保留拉丁写法。

*歧义记录*：「五件商品」是检索线索而非订单号，模拟用户不会给出订单号；中文保留。

---

### #77　items／0-1

**英文原指令**

> You name is Ivan Johnson and your zip code is 94183. You ordered a perfume and you just tried a little bit and you like it extremely. You want to get the maximum size available for it. If the agent cannot help with placing a new order, exchange your current one to the largest size available.

**中文指令**

> 你叫 Ivan Johnson，邮编 94183。你买了一瓶香水，刚试了一点点，特别喜欢。你想要它能买到的最大规格。如果客服没办法帮你重新下单，那就把你现在这瓶换成能买到的最大规格。

*逐字保留项*：`Ivan Johnson`、`94183`　*字符比*：0.31

*翻译取舍*：「just tried a little bit and you like it extremely」的细节保留——它决定了不能退货（已拆封）只能换规格。

---

### #78　cancel／2-3

**英文原指令**

> You name is Yara Muller and your email is yara.muller9246@example.com. You are sad, organized, pessimistic. For #W5056519, change address to same as #W8277957. For #W5056519, exchange Makeup Kit {'skin tone': 'light', 'kit size': 'professional', 'brand': 'Brand B'} to {'skin tone': 'dark', 'brand': 'Brand A'}; Cancel order #W5995614 because ordered by mistake.

**中文指令**

> 你叫 Yara Muller，邮箱是 yara.muller9246@example.com。你心情低落、有条理、爱往坏处想。对于订单 #W5056519，把收货地址改成和 #W8277957 一样。对于 #W5056519，把化妆套装 {「肤色」：浅色，「套装规格」：专业装，「品牌」：品牌B} 换成 {「肤色」：深色，「品牌」：品牌A}；取消订单 #W5995614，理由是下错了。

*逐字保留项*：`Yara Muller`、`yara.muller9246@example.com`、`#W5056519`、`#W8277957`、`#W5995614`、`品牌A`、`品牌B`　*字符比*：0.53

*翻译取舍*：「Brand A / Brand B」是数据库里的字面品牌名，译作「品牌A / 品牌B」保持可逆映射。三条要求用分号并列，保留原文的密集结构。

*歧义记录*：结构化规格里未给出的字段（如套装规格）应保持原值不变；中文未额外说明，与原英文一致。

---

### #83　items／0-1

**英文原指令**

> You name is Chen Silva and your zip code is 46281. You are messy, flexible, outgoing. You received two tablets and you only need one. You want to return the more expensive one and refund to credit card. If refund to credit card is not possible, you become angry and refund to GC.

**中文指令**

> 你叫 Chen Silva，邮编 46281。你大大咧咧、随和、外向。你收到两台平板，但你只需要一台。你想退掉更贵的那台，退款走信用卡。如果没法退到信用卡，你会生气，然后改成退到礼品卡。

*逐字保留项*：`Chen Silva`、`46281`　*字符比*：0.33

*翻译取舍*：「messy」译作「大大咧咧」，保留其对行为的影响（消息组织松散）。

---

### #90　cancel／0-1

**英文原指令**

> You name is Emma Kovacs and your email is emma.kovacs2974@example.com. You are polite, curious, flexible, relaxing, impatient. You want to know if the digital camera you just bought is 10x zoom. If not, modify the item to 10x zoom without changing the other options. If 10x zoom is not available, cancel the order with the reason of no longer needed. If it is available but the price is more than 3000, cancel the order with the reason of ordered by mistake.

**中文指令**

> 你叫 Emma Kovacs，邮箱是 emma.kovacs2974@example.com。你有礼貌、好奇、随和、放松、不耐烦。你想知道你刚买的那台数码相机是不是 10 倍变焦。如果不是，把商品改成 10 倍变焦、其他选项不变。如果没有 10 倍变焦可选，就以「不再需要」为由取消订单。如果有 10 倍变焦、但价格超过 3000，就以「下错了」为由取消订单。

*逐字保留项*：`Emma Kovacs`、`emma.kovacs2974@example.com`、`10`、`3000`　*字符比*：0.39

*翻译取舍*：两级条件分叉逐条保留；取消理由的原文（no longer needed / ordered by mistake）译作固定的中文说法，便于后续核对智能体是否用了对应理由。

---

### #91　items／2-3

**英文原指令**

> You name is Mei Ahmed and your zip code is 78705. You are polite, outgoing. You are angry about the quality of the two skateboards you just bought. You want to return them and refund to credit card. If the agent asks for confirmation, do not say yes, because you also want to return the smart watch. You also want to return the e-reader you just bought. If the same item is availabe online, you're willing to exchange it to the same item. If not, you want to return it and refund to credit card.

**中文指令**

> 你叫 Mei Ahmed，邮编 78705。你有礼貌、外向。你对你刚买的两块滑板的质量很生气。你想退掉它们，退款走信用卡。如果客服让你确认，你先别答应，因为你还要退智能手表。你另外还想退掉刚买的电子书阅读器。如果网上有同样的商品，你愿意换成同款。如果没有，你就想退掉、退款走信用卡。

*逐字保留项*：`Mei Ahmed`、`78705`　*字符比*：0.28

*翻译取舍*：「do not say yes」是刻意的拖延机制（逼智能体处理多件退货），译作「先别答应」，保留。

*歧义记录*：「If the same item is available online, you're willing to exchange」适用对象（滑板还是阅读器）原文不明确；中文照留歧义。

---

### #92　items／2-3

**英文原指令**

> You name is Mei Ahmed and your zip code is 78705. You are polite, outgoing. You are angry about the quality of the two skateboards you just bought. You want to return them and refund to credit card. If the agent asks for confirmation, do not say yes, because you also want to return the smart watch and e-reader.

**中文指令**

> 你叫 Mei Ahmed，邮编 78705。你有礼貌、外向。你对你刚买的两块滑板的质量很生气。你想退掉它们，退款走信用卡。如果客服让你确认，你先别答应，因为你还要退智能手表和电子书阅读器。

*逐字保留项*：`Mei Ahmed`、`78705`　*字符比*：0.3

*翻译取舍*：与 #91 是同一场景的简化变体，措辞保持平行以便配对比较。

---

### #95　items／0-1

**英文原指令**

> You name is Lei Wilson and your zip code is 32255. You are confident, organized, creative, impatient. You received a laptop and you want to exchange it to i7 processor, 8GB, 1TB SSD. If the agent asks for which laptop, it is 15-inch, 32GB.

**中文指令**

> 你叫 Lei Wilson，邮编 32255。你自信、有条理、有创意、不耐烦。你收到一台笔记本电脑，你想换成 i7 处理器、8GB 内存、1TB 固态硬盘。如果客服问是哪台笔记本，就是 15 英寸、32GB 那台。

*逐字保留项*：`Lei Wilson`、`32255`、`i7`、`8GB`、`1TB`、`15`、`32GB`　*字符比*：0.45

*翻译取舍*：规格值保留数据库写法；「32GB」出现在后半句作为辨识线索，与前半句的「8GB」形成对照，原文如此。

*歧义记录*：「8GB」与「32GB」指向不同规格维度（内存 / 已购机型），中文未加解释，保留原文的辨识难度。

---

### #105　items+address／4-5　（含输出约束）

**英文原指令**

> You name is Lucas Brown and your email is lucas.brown9344@example.com. You are busy, happy, outgoing, messy, optimistic. You want to return the bookshelf and jigsaw you received in different orders. Make sure you mention at the beginning that you want to cancel these two things, and they are from different orders. You also want to return the backpack you received with the vacuum cleaner. You also want to change your pending order item to red, and address to your default Chicago home (you won't reveal it for private reasons but it's in your profile). You want to get the tracking number of your cancelled order. You like to say one thing at a time.

**中文指令**

> 你叫 Lucas Brown，邮箱是 lucas.brown9344@example.com。你忙碌、快乐、外向、大大咧咧、乐观。你想退掉你在不同订单里收到的书架和拼图。开头一定要说明你想取消这两样东西，而且它们来自不同的订单。你还想退掉和吸尘器一起收到的那个背包。你还想把你那笔待处理订单里的商品改成红色，把地址改成你在芝加哥的默认住址（出于隐私你不想透露，但它在你资料里）。你想拿到你已取消订单的快递单号。你喜欢一次只说一件事。

*逐字保留项*：`Lucas Brown`、`lucas.brown9344@example.com`　*字符比*：0.33

*翻译取舍*：本任务 outputs 是快递单号（数字），语言中立；「一次只说一件事」是重要行为约束，保留。

*歧义记录*：原文用「cancel these two things」而真值动作是退货（return）；中文译作「取消」，与原文的措辞不一致问题一并保留。

---

### #108　items／2-3

**英文原指令**

> You name is Yara Ito and your zip code is 75284. You are happy, messy. Your received hiking boots but seem like already worn, you are unhappy about it and want to send for a new pair with the same specs. You also want to exchange your jigsaw to a more fancy theme, with 500 pieces less. But you want to keep the same difficulty level.

**中文指令**

> 你叫 Yara Ito，邮编 75284。你快乐、大大咧咧。你收到一双登山靴，但看起来像是被人穿过了，你很不满，想换成一双规格完全一样的新靴子。你还想把你的拼图换成一个更花哨的主题，片数少 500 片。但你想保持同样的难度等级。

*逐字保留项*：`Yara Ito`、`75284`、`500`　*字符比*：0.34

*翻译取舍*：「500 pieces less」是相对量（不是绝对值），中文用「少 500 片」保留相对表述。

*歧义记录*：「more fancy theme」无客观标准，需模拟用户自己把握；中文保留同一开放度。

---

### #112　items+address／2-3

**英文原指令**

> You name is Yara Silva and your zip code is 77159. You are sad and cautious. You want to modify the laptop order to your NYC address (you don't want to reveal it but should be in your orders profile). You also like to modify the laptop to be {'processor': 'i5', 'storage': '256GB SSD', 'color': 'space grey'};  You also want to exchange your watch to be black dial color but keep the leather strap. You like to say things together.

**中文指令**

> 你叫 Yara Silva，邮编 77159。你心情低落、谨慎。你想把笔记本电脑那笔订单改送到你在纽约的地址（你不想透露，但它应该在你的订单资料里）。你还想把这台笔记本改成 {「处理器」：i5，「存储」：256GB 固态硬盘，「颜色」：深空灰}。你还想把你的手表换成黑色表盘，但保留皮表带。你喜欢把事情一起说。

*逐字保留项*：`Yara Silva`、`77159`、`i5`、`256GB`　*字符比*：0.36

*翻译取舍*：「纽约的地址」要求智能体从订单资料里自己找，不直接给地址。

---

### #113　items+address／2-3

**英文原指令**

> You name is Yara Silva and your zip code is 77159. You are sad and cautious. You want to modify the laptop order to your NYC address (you don't want to reveal it but should be in your orders profile). You also like to modify the laptop to be 9844888101. You also want to exchange your watch to be black dial color but keep the leather strap. You like to say things piecewise.

**中文指令**

> 你叫 Yara Silva，邮编 77159。你心情低落、谨慎。你想把笔记本电脑那笔订单改送到你在纽约的地址（你不想透露，但它应该在你的订单资料里）。你还想把这台笔记本改成 9844888101。你还想把你的手表换成黑色表盘，但保留皮表带。你喜欢一件一件地说。

*逐字保留项*：`Yara Silva`、`77159`、`9844888101`　*字符比*：0.35

*翻译取舍*：「9844888101」是商品变体 ID，必须逐字保留。与 #112 的唯一差别是：用变体 ID 代替规格描述，以及「一起说 / 一件一件说」的表述节奏不同——这一对是刻意保留的对照组。

---

