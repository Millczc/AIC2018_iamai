import os
import glob
import sys
import torch
from torch.autograd import Variable
from torch.utils.data import Dataset,DataLoader
from torch.utils.data.sampler import SubsetRandomSampler
from torchvision import transforms
from torchvision.transforms import Compose,Resize,ToTensor
from PIL import Image,ImageEnhance
import time as time
import models
import numpy as np
import torchvision.utils as vutils

class VReID_Dataset(Dataset):
    def __init__(self, txt_file,resize=(224,224),crop=False,flip=False,jitter=0,pretrained_model=True,dataset='VeRi'):
        
        ######################
        self.img_list = []
        self.label_list = []
        self.color_list = []
        self.type_list = []
        self.dataset = dataset
        file = open(txt_file,'r')
        for row in file:
            line = row.strip().split(' ')
            self.img_list.append(line[0])
            self.label_list.append(int(line[1])-1)
            if self.dataset == 'VeRi_ict':
                self.color_list.append(int(line[2])-1)
                self.type_list.append(int(line[3])-1)
        file.close()
        self.n_id = len(set(self.label_list))
        
        if self.dataset=='VeRi_ict':
            self.n_color = len(set(self.color_list))
            self.n_type = len(set(self.type_list))
        else:
            self.n_color = 0
            self.n_type = 0
        index = np.random.permutation(len(self.label_list))
        # np.save('train_val_index.npy',index)
        # exit(-1)
        # print(self.n_id)
        index = np.load('train_val_index.npy')
        n_train = int(0.95*len(self.label_list))
        n_val = len(self.label_list)-n_train
        self.train_index = list(index[:n_train])
        self.val_index = list(index[-n_val:])
        self.n_train = len(self.train_index)
        self.n_val = len(self.val_index)

        #####################
        tran = []
        if crop == True:
            tran.append(transforms.Resize((resize[0]+50,resize[1]+50)))
            tran.append(transforms.RandomCrop(resize))
        else:
            tran.append(transforms.Resize(resize))
        if flip == True:
            tran.append(transforms.RandomHorizontalFlip())
        if jitter != 0:
            tran.append(transforms.ColorJitter(brightness=jitter))
        tran.append(transforms.ToTensor())
        if pretrained_model == True:
            tran.append(transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                              std=[0.229, 0.224, 0.225]))
        self.compose = transforms.Compose(tran)
    def __getitem__(self,idx):
        img_name,label = self.img_list[idx],self.label_list[idx]
        img = Image.open(img_name)
        img = self.compose(img)
        if self.dataset == 'VeRi_ict':
            color = self.color_list[idx]
            type = self.type_list[idx]
            return{'img':img,'gt':torch.LongTensor([label]),'color':torch.LongTensor([color]),'type':torch.LongTensor([type])}
        return {'img':img,'gt':torch.LongTensor([label])}

    def __len__(self):
        return len(self.img_list)
            
class TripletImage_Dataset(Dataset):
    def __init__(self, db_txt, resize=(224,224), crop=False, flip=False, jitter=False, 
                 imagenet_normalize=True, val_split=0.01, 
                 class_in_batch=32, image_per_class_in_batch=4):

        # Load image list, class list
        txt = np.loadtxt(db_txt, dtype=str)
        self.imgs = txt[:, 0]
        self.classes, self.n_id = Remap_Label(txt[:, 1].astype(int))
        if not Check_Min_Sample_Per_Class(self.classes, image_per_class_in_batch): 
            return ValueError('There is not enough samples per class! (Min {} samples required)'\
                              .format(image_per_class_in_batch))
        self.len = self.n_id
        self.class_in_batch = class_in_batch
        self.image_per_class_in_batch = image_per_class_in_batch

        # Validation split (split according to id)
        permute_idx = np.random.permutation(self.n_id)
        self.val_index = permute_idx[:int(val_split*self.n_id)]
        self.train_index = permute_idx[int(val_split*self.n_id):]
        self.n_train = int(self.len * (1-val_split))
        self.n_val = int(self.len * val_split)

        # Transform
        self.jitter = jitter
        trans_PIL = []
        if crop:
            trans_PIL.append(transforms.Resize((resize[0]+50, resize[1]+50)))
            trans_PIL.append(transforms.RandomCrop(resize))
        else:
            trans_PIL.append(transforms.Resize(resize))
        if flip: trans_PIL.append(transforms.RandomHorizontalFlip())
        trans_Tensor = []
        if not self.jitter: 
            trans_Tensor.append(transforms.ToTensor())
        if imagenet_normalize:
            trans_Tensor.append(transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]))
        self.transform_PIL = transforms.Compose(trans_PIL)
        self.transform_Tensor = transforms.Compose(trans_Tensor)
        
    def __getitem__(self, idx):
        id = torch.arange(self.n_id).long()[idx]
        final_idx = np.zeros((self.image_per_class_in_batch,))
        select = np.nonzero(self.classes == id)[0]
        select = np.random.permutation(select)[:self.image_per_class_in_batch]
        output = {'img':[], 'class':[]}
        for i in select.tolist():
            img = Image.open(self.imgs[i])
            if self.jitter:
                img = self.transform_PIL(img)
                img = Jitter_Transform_to_Tensor(img)
                img = self.transform_Tensor(img)
            else:
                img = self.transform_Tensor(self.transform_PIL(img))
            output['img'].append(img.unsqueeze(0))
            output['class'].append(id)
        output['img'] = torch.cat(output['img'], dim=0)
        output['class'] = torch.LongTensor(output['class'])
        return output

    def __len__(self):
        return self.len

def Get_train_DataLoader(dataset,batch_size=128,shuffle=True,num_workers=6):
    sampler = SubsetRandomSampler(dataset.train_index)
    return DataLoader(dataset,batch_size = batch_size,sampler=sampler,num_workers=6)

def Get_val_DataLoader(dataset,batch_size=128,shuffle=True,num_workers=6):
    sampler = SubsetRandomSampler(dataset.val_index)
    return DataLoader(dataset,batch_size = batch_size,sampler=sampler,num_workers=6)

def Remap_Label(labels):
    labels = labels - np.min(labels)
    unique_label = np.unique(labels)
    label_map = np.zeros(np.max(unique_label)+1, dtype=int)
    for i, l in enumerate(unique_label.tolist()):
        label_map[l] = i
    return label_map[labels], len(unique_label)

def Check_Min_Sample_Per_Class(labels, min):
    unique_labels = np.unique(labels)
    for i in unique_labels.tolist():
        if (labels == i).sum() < min:
            return False
    return True


def Jitter_Transform_to_Tensor(img_):
    coin = np.random.uniform(0,1)
    coin = 0.9
    if coin> 0.4 and coin < 0.7: #normal
        i_factor = 1
        c_factor = 1
        r_factor = 1
        b_factor = 1
    elif coin <= 0.2: #high shadow blue
        i_factor = 0.6
        c_factor = 0.8
        r_factor = 0.9
        b_factor = 1.3
    elif coin > 0.2 and coin <= 0.4: #little shadow blue
        i_factor = 0.7
        c_factor = 0.7
        r_factor = 0.9
        b_factor = 1.2
    elif coin >= 0.7 and coin<0.8: #little bright
        i_factor = 1.2
        c_factor = 1.2
        r_factor = 1
        b_factor = 1
    elif coin >= 0.8 and coin<0.9: # little yellow
        i_factor = 0.7
        c_factor = 0.7
        r_factor = 1.2
        b_factor = 0.9
    elif coin >= 0.9 and coin <1: # higher shadow yellow
        i_factor = 0.6
        c_factor = 0.6
        r_factor = 1.4
        b_factor = 0.8
    enhancer_br = ImageEnhance.Brightness(img_)
    img = enhancer_br.enhance(i_factor)
    enhancer_con = ImageEnhance.Contrast(img)
    img = enhancer_con.enhance(c_factor)

    totensor = transforms.ToTensor()
    img = totensor(img)
    img[0,:,:] *=r_factor
    img[2,:,:] *=b_factor
    return img    
    
# def generating_train_test_info():
    # label_list = []
    # file = open('train_info.txt','r')
    # file_content = file.readlines()
    # for row in file_content:
        # img,label = row.strip().split(' ')
        # label_list.append(label)
    # n_id = len(set(label_list))
    # test_id = list(np.random.permutation(n_id)[:int(0.3*n_id)])
    
    # train_label_dict = {}
    # test_label_dict = {}
    # tr_file = open('real_train_info.txt','w')
    # te_file = open('real_test_info.txt','w')
    # train_count = 0
    # test_count = 0
    # for row in file_content:
        # img,label = row.strip().split(' ')
        # if int(label) not in test_id:
            # if label not in train_label_dict:
                # train_label_dict[label]=train_count
                # train_count += 1
                # tr_file.write(img+' '+str(train_label_dict[label])+'\n')
            # else:
                # tr_file.write(img+' '+str(train_label_dict[label])+'\n')
        # else:
            # if label not in test_label_dict:
                # test_label_dict[label]=test_count
                # test_count +=1
                # te_file.write(img+' '+str(test_label_dict[label])+'\n')
            # else:
                # te_file.write(img+' '+str(test_label_dict[label])+'\n')

if __name__ == '__main__':
    re = transforms.Resize((224,224))
    '''This part
    totensor = transforms.ToTensor()
    brightness_factor = float(sys.argv[2])
    contrast_factor = float(sys.argv[3])
    hue_factor = float(sys.argv[4])

    img = Image.open(sys.argv[1])
    img = re(img)

    enhancer_br = ImageEnhance.Brightness(img)
    img = enhancer_br.enhance(brightness_factor)
    enhancer_con = ImageEnhance.Contrast(img)
    img = enhancer_con.enhance(contrast_factor)
    img = totensor(img)
    vutils.save_image(img,'testimg.jpg')
    exit(-1)
    '''

    '''And This part
    img = Image.open(sys.argv[1])
    re = transforms.Resize((224,224))
    img = re(img)
    img = Jitter_Transform_to_Tensor(img)
    vutils.save_image(img,'testimg.jpg')
    exit(-1)
    # '''
    # '''
    # pretrained = True

    # D = VReID_Dataset(sys.argv[1],crop=True,flip=True,pretrained_model=pretrained)
    # loader = Get_DataLoader(D)

    # print('len:',len(D))
    # print('n_id:',D.n_id)
    # print('n_batch:',len(D)//128+1)
    #labels = (np.arange(10)+1)*10
    #print(labels)
    #labels = Remap_Label(labels)
    #print(labels)

    dataset = TripletImage_Dataset(sys.argv[1], crop=True, flip=True, jitter=True, imagenet_normalize=True)
    train_loader = Get_train_DataLoader(dataset, batch_size=32, num_workers=1)
    val_loader = Get_val_DataLoader(dataset, batch_size=32)
    print('len', len(dataset))
    print('train n_batch', len(train_loader))
    print('val n_batch', len(val_loader))
    for data in train_loader:
       print(data.keys())
       print(data['img'][0].size())
       print(data['class'][0].size())
       vutils.save_image(data['img'][0][0],'testimg.jpg')

       exit(-1)
    for data in val_loader:
       print(data.keys())
       print(data['img'])
       print(data['class'])
    # '''


