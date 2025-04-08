# 邮件分类器项目

## 项目概述
本项目实现了一个基于机器学习的邮件分类器，能够将邮件分类为垃圾邮件或普通邮件。项目支持两种特征提取方式：高频词特征和TF-IDF加权特征。

## 核心功能说明

### 1. 高频词特征提取
高频词特征提取方法通过统计邮件中高频词的出现次数来构建特征向量。

```python
def get_top_words(top_num):
    """遍历邮件建立词库后返回出现次数最多的词"""
    filename_list = ['邮件_files/{}.txt'.format(i) for i in range(151)]
    all_words = []
    for filename in filename_list:
        all_words.append(get_words(filename))
    freq = Counter(chain(*all_words))
    return [i[0] for i in freq.most_common(top_num)]

<img src="https://github.com/hhfyx/hhf/blob/master/image/%E5%B1%8F%E5%B9%95%E6%88%AA%E5%9B%BE%202025-04-08%20180047.png" width="800" alt="截图一">
<img src="https://github.com/hhfyx/hhf/blob/master/image/%E5%B1%8F%E5%B9%95%E6%88%AA%E5%9B%BE%202025-04-08%20180058.png" width="800" alt="截图二">