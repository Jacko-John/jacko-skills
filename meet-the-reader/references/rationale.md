# 设计依据与边界

这份 skill 把“人类容易理解的沟通结构”作为无条件先验，再把学习科学里的证据当作调整起点的方向，而不是把对话伪装成精确的学习测量。

## 两层设计的原因

- **先验基线先于个体适配。** 即便读者已是某个领域的专家，只要他当下没有你的内部上下文，跳跃指代、先扔结论后补动机、混写已验证事实与未验证推测，依然会造成理解负担。由浅入深、上下文自足、用同一具体例子串联现象与原因，是对所有人成立的认知可读性条件。
- **先验知识决定锚点位置，而非取消叙事骨架。** Expertise reversal 研究提示，对新手有帮助的冗余基础支架，对有经验者未必有益。这支持跳过对方已掌握的前置定义、直接把已知机制用作具体例子的锚点，而不是在面对熟手时省去背景交代、步骤衔接与证据区分。
- **正确答案不等于正确理解。** “Correct Answer Trap”在 Eedi 数学作答与模型评估中发现，错误推理有时碰巧得到正确答案，模型也会漏检。这里只借用“别把结果当作推理”的提醒，不将其检测结果推广成通用评分规则。
- **对话顺畅不等于指代一致。** “Mind the Gap”研究对话中的指称与信念分歧，区分 surface coordination 和 epistemic alignment。它支持关注隐蔽的误解，但其表征消融实验不是术语教学效果的证据。
- **“懂了”需要结合行为来看。** 解释性理解错觉研究提示，人可能高估自己的理解。自我报告仍有校准价值，只是不宜单独当作掌握证明。
- **在教学互动中留一个可接手的落点，但别把对话变成考场。** Chi 等人的自我解释研究发现，学得好的学生会主动解释例题中的步骤并发现自己理解上的缺口。这支持在辅导或深入学习场景把讲解落在一个推论或例子上；它研究的是学生自发的解释，不意味着应当要求用户复述，更不适用于常规汇报与工程问答。

## 本 skill 的启发式

以下是设计选择，不是上述研究验证出的算法：

- 所有面向人类的输出默认自足、由浅入深、先人话后术语、步步相接、事实与推断分层。
- 只按知识领域保存跨项目可复用的少量观察与讲解偏好，以“能改变下一次讲法”为记录标准，剥离课程、作业编号与会话流水账。
- 区分可暂时依赖的已知与待校准信号，让新证据能够修正旧判断。
- 给记录标注日期，只用来提醒“这条可能需要重新留意”，不据此自动降级。
- 误区在核实后才记录，纠正并能正确运用后移除，避免变成永久标签。
- 无档案或处于只读环境时直接利用当前对话校准，不为建档或写档打断任务。

## 明确不做

不估计掌握概率，不使用 FSRS/BKT，不按时间自动降级，不建立固定升级公式。一次正确或失败往往只反映特定情境；间隔重复算法也不能直接证明对话中的能力状态。

不做完整知识地图、学习风格标签、多 agent 状态机或复习计划。全局档案只是供讲解参考的工作底稿，不是心理画像，也不保证跨会话推断正确。

## 来源

- Kalyuga, S., Ayres, P., Chandler, P., & Sweller, J. (2003). The expertise reversal effect. *Educational Psychologist*, 38(1), 23–31. https://doi.org/10.1207/S15326985EP3801_4
- Rozenblit, L., & Keil, F. (2002). The misunderstood limits of folk science: An illusion of explanatory depth. *Cognitive Science*, 26(5), 521–562. https://doi.org/10.1207/s15516709cog2605_1
- Catching The Correct Answer Trap: Characterising AI Tutor Blind Spots When Analysing Student Reasoning. https://arxiv.org/abs/2605.23925
- Zhu, Y., Rim, K., & Pustejovsky, J. (2026). Mind the Gap: Theory-of-Mind-Grounded Friction for Epistemic Alignment. *Findings of EMNLP 2026*. https://aclanthology.org/2026.findings-emnlp.605/
- Chi, M. T. H., Bassok, M., Lewis, M. W., Reimann, P., & Glaser, R. (1989). Self-explanations: How students study and use examples in learning to solve problems. *Cognitive Science*, 13(2), 145–182. https://onlinelibrary.wiley.com/doi/pdf/10.1207/s15516709cog1302_1
