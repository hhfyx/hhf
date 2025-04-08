import re
import os
from jieba import cut
from itertools import chain
from collections import Counter
import numpy as np
from sklearn.naive_bayes import MultinomialNB
from sklearn.feature_extraction.text import TfidfVectorizer


def get_words(filename):
    """读取文本并过滤无效字符和长度为1的词"""
    words = []
    with open(filename, 'r', encoding='utf-8') as fr:
        for line in fr:
            line = line.strip()
            line = re.sub(r'[.【】0-9、——。，！~\*]', '', line)
            line = cut(line)
            line = filter(lambda word: len(word) > 1, line)
            words.extend(line)
    return words


def get_top_words(top_num):
    """遍历邮件建立词库后返回出现次数最多的词"""
    filename_list = ['邮件_files/{}.txt'.format(i) for i in range(151)]
    all_words = []
    for filename in filename_list:
        all_words.append(get_words(filename))
    freq = Counter(chain(*all_words))
    return [i[0] for i in freq.most_common(top_num)]


def extract_features(feature_type='tfidf', top_num=100):
    """特征提取函数，支持高频词特征和TF-IDF特征的选择"""
    filename_list = ['邮件_files/{}.txt'.format(i) for i in range(151)]

    if feature_type == 'tfidf':
        texts = []
        for filename in filename_list:
            with open(filename, 'r', encoding='utf-8') as fr:
                texts.append(fr.read())

        vectorizer = TfidfVectorizer(
            analyzer='word',
            tokenizer=lambda x: list(cut(x)),
            preprocessor=lambda x: re.sub(r'[.【】0-9、——。，！~\*]', '', x),
            token_pattern=r'(?u)\b\w+\b',
            max_features=top_num
        )
        vector = vectorizer.fit_transform(texts)
        return vector.toarray(), vectorizer
    else:
        top_words = get_top_words(top_num)
        vector = []
        for filename in filename_list:
            words = get_words(filename)
            word_map = list(map(lambda word: words.count(word), top_words))
            vector.append(word_map)
        return np.array(vector), None


def train_model(feature_type='tfidf', top_num=100):
    """训练模型函数，支持特征选择"""
    vector, vectorizer = extract_features(feature_type, top_num)
    labels = np.array([1] * 127 + [0] * 24)
    model = MultinomialNB()
    model.fit(vector, labels)
    return model, vectorizer, top_words if feature_type == 'high_freq' else None


def predict(filename, model, vectorizer=None, top_words=None, feature_type='tfidf'):
    """对未知邮件分类"""
    if feature_type == 'tfidf':
        with open(filename, 'r', encoding='utf-8') as fr:
            text = fr.read()
        text = re.sub(r'[.【】0-9、——。，！~\*]', '', text)
        current_vector = vectorizer.transform([text]).toarray()
    else:
        words = get_words(filename)
        current_vector = np.array(tuple(map(lambda word: words.count(word), top_words)))

    result = model.predict(current_vector.reshape(1, -1))
    return '垃圾邮件' if result == 1 else '普通邮件'


# 训练模型
model, vectorizer, top_words = train_model(feature_type='tfidf', top_num=100)

# 预测
print('151.txt分类情况:{}'.format(predict('邮件_files/151.txt', model, vectorizer, feature_type='tfidf')))
print('152.txt分类情况:{}'.format(predict('邮件_files/152.txt', model, vectorizer, feature_type='tfidf')))
print('153.txt分类情况:{}'.format(predict('邮件_files/153.txt', model, vectorizer, feature_type='tfidf')))
print('154.txt分类情况:{}'.format(predict('邮件_files/154.txt', model, vectorizer, feature_type='tfidf')))
print('155.txt分类情况:{}'.format(predict('邮件_files/155.txt', model, vectorizer, feature_type='tfidf')))