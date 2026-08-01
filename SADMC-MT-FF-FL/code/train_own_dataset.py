import sys
import os
import torch
import torch.utils.data.dataloader as dataloader
from torch.utils.data import Dataset
import torch.nn as nn
import torch.optim as optim
import numpy as np
import network_fed as net
import random
import time
import math
from sklearn.metrics import classification_report, confusion_matrix

CLASS_NAMES = ['NORMAL', 'CPU_HOG', 'MEMORY_LEAK', 'NETWORK_LATENCY']

list_names_1 = []
list_names_2 = []

def print_class_report(name, y_true, y_pred):
    labels_present = sorted(set(y_true) | set(y_pred))
    print("--- {} per-class report (best epoch) ---".format(name))
    print(classification_report(
        y_true, y_pred,
        labels=labels_present,
        target_names=[CLASS_NAMES[i] for i in labels_present],
        digits=3, zero_division=0,
    ))
    print("Confusion matrix (rows=true, cols=pred), classes:", [CLASS_NAMES[i] for i in labels_present])
    print(confusion_matrix(y_true, y_pred, labels=labels_present))

def setup_seed(seed):
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)
    random.seed(seed)
    torch.backends.cudnn.deterministic = True


class LoadData(Dataset):
    def __init__(self, train_x, train_y):
        self.train_x = train_x
        self.train_y = train_y
        self.len = len(self.train_x)

    def __getitem__(self, index):
        return self.train_x[index], self.train_y[index]

    def __len__(self):
        return self.len

def train_and_test(class_name, train_loader, test_loader, num_classes, length):
    epoches = 100
    lr = 0.001
    input_num = 1
    name = class_name.rstrip('.csv')
    list_names_1.append(name)
    print(name)
    loss_list = []
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    model = net.BasicFCN(input_num, num_classes, length)
    model.to(device)

    optimizer = optim.AdamW(model.parameters(), lr=lr)
    loss_func = nn.CrossEntropyLoss()

    acc = 0
    correct = 0
    total = 0
    model_Tstate = None
    best_y_true = None
    best_y_pred = None

    for epoch in range(epoches):
        epoch_loss_list = []
        for images, labels in train_loader:
            model.train()
            images = images.to(device)
            labels = labels.to(device)
            images = images.float()
            output = model(images)
            loss = loss_func(output, labels)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            epoch_loss_list.append(loss.cpu().detach().numpy())

        model.eval()
        correct = 0
        total = 0
        epoch_y_true = []
        epoch_y_pred = []
        with torch.no_grad():
            for images, labels in test_loader:
                images = images.to(device)
                labels = labels.to(device)
                images = images.float()
                output = model(images)
                values, predicte = torch.max(output, 1)
                total += labels.size(0)
                correct += (predicte == labels).sum().item()
                epoch_y_true.append(labels.cpu().numpy())
                epoch_y_pred.append(predicte.cpu().numpy())
        if total > 0 and (correct / total) > acc:
            acc = correct / total
            model_Tstate = model
            best_y_true = np.concatenate(epoch_y_true)
            best_y_pred = np.concatenate(epoch_y_pred)

        loss_list.append(np.mean(epoch_loss_list))

    print("{} final test acc: {:.3f}".format(name, acc))
    if best_y_true is not None:
        print_class_report(name, best_y_true, best_y_pred)
    return model_Tstate


def train_and_test_load(class_name, train_loader, test_loader, num_classes, length, index, FCNmodel):
    epoches = 100
    lr = 0.001
    input_num = 1
    name = class_name.rstrip('.csv')
    list_names_2.append(name)
    print(name)
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    index = FCNmodel.StoreEW(index, top_k=2)
    parameterlist = FCNmodel.LoadParameters(index[0])

    model = net.MLSTM(length, num_classes, parameterlist)
    model.to(device)
    optimizer = optim.AdamW(model.parameters(), lr=lr)
    loss_func = nn.CrossEntropyLoss()

    acc = 0
    correct = 0
    total = 0
    model_Rstate = None
    best_y_true = None
    best_y_pred = None

    for epoch in range(epoches):
        for images, labels in train_loader:
            model.train()
            images = images.to(device)
            labels = labels.to(device)
            output = model(images)
            loss = loss_func(output, labels)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        model.eval()
        correct = 0
        total = 0
        epoch_y_true = []
        epoch_y_pred = []
        with torch.no_grad():
            for images, labels in test_loader:
                images = images.to(device)
                labels = labels.to(device)
                pre_out = model(images)
                values, predicte = torch.max(pre_out, 1)
                total += labels.size(0)
                correct += (predicte == labels).sum().item()
                epoch_y_true.append(labels.cpu().numpy())
                epoch_y_pred.append(predicte.cpu().numpy())
        if total > 0 and (correct / total) > acc:
            acc = correct / total
            model_Rstate = model
            best_y_true = np.concatenate(epoch_y_true)
            best_y_pred = np.concatenate(epoch_y_pred)

    print("{} final test acc: {:.3f}".format(name, acc))
    if best_y_true is not None:
        print_class_report(name, best_y_true, best_y_pred)
    return model_Rstate


DATA_DIR = "../Mul_Class_Data_own"
dir_name = ['carts.csv', 'catalogue.csv', 'front-end.csv', 'orders.csv', 'payment.csv', 'shipping.csv', 'user.csv']

setup_seed(123)
Fed_iteration = 4
names = dir_name
start_time = time.time()

for i in range(len(names)):
    classname = names[i]
    x_train = np.load(f"{DATA_DIR}/{classname}_Xtrain.npy")
    y_train = np.load(f"{DATA_DIR}/{classname}_Ytrain.npy")
    x_test = np.load(f"{DATA_DIR}/{classname}_Xtest.npy")
    y_test = np.load(f"{DATA_DIR}/{classname}_Ytest.npy")
    num_classes = y_test.shape[1]
    length = x_train.shape[1]
    y_test = np.argmax(y_test, axis=1)
    y_train = np.argmax(y_train, axis=1)
    print(x_train.shape, y_train.shape)
    x_train = x_train.reshape((x_train.shape[0], 1, x_train.shape[1])).astype(np.float32)
    x_test = x_test.reshape((x_test.shape[0], 1, x_test.shape[1])).astype(np.float32)
    train_loader = dataloader.DataLoader(dataset=LoadData(x_train, y_train), batch_size=128, shuffle=True)
    test_loader = dataloader.DataLoader(dataset=LoadData(x_test, y_test), shuffle=False)
    print("Load---------dataset:", classname)
    if i == 0:
        model_state = train_and_test(classname, train_loader, test_loader, num_classes, length)
        shared = net.StoreParameters()
        shared.Appended(model_state)
    else:
        model_stateL = train_and_test(classname, train_loader, test_loader, num_classes, length)
        shared.Appended(model_stateL)
    print("Dataset:%s eslapsed %.5f mins" % (classname, (time.time() - start_time) / 60))

for e in range(1, Fed_iteration):
    FCNmodel = shared
    print("Fed Task------------%d" % (e + 1))
    for i in range(len(names)):
        classname = names[i]
        x_train = np.load(f"{DATA_DIR}/{classname}_Xtrain.npy")
        y_train = np.load(f"{DATA_DIR}/{classname}_Ytrain.npy")
        x_test = np.load(f"{DATA_DIR}/{classname}_Xtest.npy")
        y_test = np.load(f"{DATA_DIR}/{classname}_Ytest.npy")
        num_classes = y_test.shape[1]
        length = x_train.shape[1]
        y_test = np.argmax(y_test, axis=1)
        y_train = np.argmax(y_train, axis=1)
        x_train = x_train.reshape((x_train.shape[0], 1, x_train.shape[1])).astype(np.float32)
        x_test = x_test.reshape((x_test.shape[0], 1, x_test.shape[1])).astype(np.float32)
        train_loader = dataloader.DataLoader(dataset=LoadData(x_train, y_train), batch_size=128, shuffle=True)
        test_loader = dataloader.DataLoader(dataset=LoadData(x_test, y_test), shuffle=False)
        print("Load---------dataset:", classname)
        if i == 0:
            model_stateP = train_and_test_load(classname, train_loader, test_loader, num_classes, length, i, FCNmodel)
            shared = net.StoreParameters()
            shared.Appended(model_stateP)
        else:
            model_stateV = train_and_test_load(classname, train_loader, test_loader, num_classes, length, i, FCNmodel)
            shared.Appended(model_stateV)
        print("Dataset:%s eslapsed %.5f mins" % (classname, (time.time() - start_time) / 60))

# Save the trained global model separately from the paper-dataset model
# (saved_models/sadmc_global_model.pth) so the production SaaS model is left untouched.
os.makedirs("../saved_models", exist_ok=True)
avg_params = shared.getAvgParameter(len(names))
global_model = net.MLSTM(length, num_classes, avg_params)
torch.save(global_model.state_dict(), "../saved_models/sadmc_global_model_own.pth")
print("\n[SUCCESS] Federated training complete. Saved global model to '../saved_models/sadmc_global_model_own.pth'")
print("Total elapsed %.2f mins" % ((time.time() - start_time) / 60))
