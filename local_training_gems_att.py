import torch
from pseudo_labeling_att import obtain_cnn_centroid_feature,obtain_cnn_source_centroid_feature,obtain_cnn_confidence_index,gems_centroid
import os
from utils import loop_iterable
from contrastive_loss import SupConLoss
criterion_1 = torch.nn.CrossEntropyLoss()
criterion_2 = SupConLoss()
def lcoal_training(model,optim,lr_schedule,idx,source_loader,labeled_loader,unlabeled_loader, epochs,iterations):
    # print('idx',idx)
    # os.environ["CUDA_VISIBLE_DEVICES"] =  str(idx)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    # print('device',device)
    # torch.cuda.set_per_process_memory_fraction(0.0, 0)
    # torch.cuda.empty_cache()
    model = model.to(device)
    # if data_name == 'imagenet':
    #         model_ = resnet50(pretrained=True)
    #         model = model_.to(device)
    # if data_name == 'cifar-10':
    #     model_ = resnet18(pretrained=True)
    #     model = model_.to(device)
    # if data_name == 'mnist':
    #     model = Net().to(device)
    # optim = torch.optim.Adam(model.parameters())
    # lr_schedule = torch.optim.lr_scheduler.ReduceLROnPlateau(optim, patience=1, verbose=True)

    for epoch in range(1, epochs+1):
        #     batch_iterator = zip(loop_iterable(source_loader), loop_iterable(target_loader))
        batch_iterator = zip(loop_iterable(source_loader),loop_iterable(labeled_loader) ,loop_iterable(unlabeled_loader))
        for ind in range(iterations):
            (x, y_true), (labeled_x,labeled_aug_data, y_target),(unlabeled_x,unlabeled_aug_data, unlabeled_label) = next(batch_iterator)
            x, y_true = x.to(device), y_true.to(device)
            labeled_x,y_target =  labeled_x.to(device), y_target.to(device)
            labeled_all = torch.cat([x, labeled_x], dim=0)
            target_all = torch.cat([y_true, y_target], dim=0)
            # print('labeled_all',labeled_all.shape)
            # print('target_all',target_all)
            labeled_all = labeled_all.to(torch.float32)
            target_all = target_all.to(torch.long)
            _,y_pred,__,___ = model(labeled_all)
            loss_ce = criterion_1(y_pred, target_all)
            if epoch ==1 and ind<200:
                loss = loss_ce
                optim.zero_grad()
                loss.backward()
                optim.step()
                del loss
                torch.cuda.empty_cache()
            else:
                ###### confident_supervised_contrastive_loss_calculation ####
                condifent_index, unconfident_index, pseudo_label = obtain_cnn_confidence_index(model, unlabeled_x, unlabeled_label, ind,epoch,True)
                confident_sample = unlabeled_x[condifent_index]
                confident_aug_sample = unlabeled_aug_data[condifent_index]
                confident_sample=confident_sample.to(device)
                confident_aug_sample=confident_aug_sample.to(device)
                confident_sample_more = torch.cat([confident_sample,labeled_x])
                labeled_aug_data=labeled_aug_data.to(device)
                confident_sample_aug_more = torch.cat([confident_aug_sample,labeled_aug_data])
                del confident_aug_sample, labeled_aug_data
                torch.cuda.empty_cache()
                unconfident_sample = unlabeled_x[unconfident_index]
                unconfident_aug_sample = unlabeled_aug_data[unconfident_index]
                images = torch.cat([confident_sample_more, confident_sample_aug_more], dim=0)
                del confident_sample_aug_more
                torch.cuda.empty_cache()
                if images.shape[0]!=0:
                    pseudo_label = torch.tensor(pseudo_label).to(device)
                    confident_label_more = torch.cat([pseudo_label,y_target])
                    if torch.cuda.is_available():
                        images = images.cuda(non_blocking=True)
                        confident_label_more = confident_label_more.cuda(non_blocking=True)
                    bsz_1 = confident_sample_more.shape[0]
                    _, _, _,features_norm = model(images)
                    
                    f1, f2 = torch.split(features_norm, [bsz_1, bsz_1], dim=0)
                    features = torch.cat([f1.unsqueeze(1), f2.unsqueeze(1)], dim=1)
                    del _,f1, f2,features_norm
                    torch.cuda.empty_cache()
                    sup_condifent_loss_contrastive = criterion_2(features, confident_label_more)
                ###### unconfident_contrastive_loss_calculation ####

                images_unconfident = torch.cat([unconfident_sample, unconfident_aug_sample], dim=0)
                if images_unconfident.shape[0]!=0:
                    if torch.cuda.is_available():
                        images_unconfident = images_unconfident.cuda(non_blocking=True)
                        # labels = labels.cuda(non_blocking=True)
                    bsz = unconfident_sample.shape[0]
                    _, __, _,features_norm = model(images_unconfident)
                    f1_unconfident, f2_unconfident = torch.split(features_norm, [bsz, bsz], dim=0)
                    features_unconfident = torch.cat([f1_unconfident.unsqueeze(1), f2_unconfident.unsqueeze(1)], dim=1)
                    # print('features_unconfident',features_unconfident.shape)
                    del _,__,f1_unconfident, f2_unconfident,features_norm
                    torch.cuda.empty_cache()
                    unconfident_unsup_loss_contrastive = criterion_2(features_unconfident)
                    del features_unconfident
                    torch.cuda.empty_cache()

                ###### supervised_contrastive_centroid_alignment ####
                sor_centroid, _ = obtain_cnn_source_centroid_feature(model,x,y_true)
                centroid_label = torch.tensor([0,1])
                if confident_sample.shape[0]!=0 and unconfident_sample.shape[0]!=0:
                    confident_unlabeled_centroid,_ = obtain_cnn_centroid_feature(model,confident_sample)
                    unconfident_unlabeled_centroid,_ = obtain_cnn_centroid_feature(model,unconfident_sample)
                # unlabeled_centroid, _ = obtain_cnn_centroid_feature(model,unlabeled_x)
                
                    confident_unlabeled_centroid = torch.tensor(confident_unlabeled_centroid)
                    unconfident_unlabeled_centroid = torch.tensor(unconfident_unlabeled_centroid)
                    sor_centroid = torch.tensor(sor_centroid)
                    centroid_features_1 = torch.cat([confident_unlabeled_centroid.unsqueeze(1),sor_centroid.unsqueeze(1)], dim=1)
                    centroid_features_2 = torch.cat([unconfident_unlabeled_centroid.unsqueeze(1),sor_centroid.unsqueeze(1)], dim=1)
                # print('centroid_features',centroid_features.shape)
                    centroid_contrastive_1= criterion_2(centroid_features_1,centroid_label)
                    centroid_contrastive_2= criterion_2(centroid_features_2,centroid_label)
                    # print('centroid_contrastive_1',centroid_contrastive_1.item())
                    # print('centroid_contrastive_2',centroid_contrastive_2.item())
                    centroid_contrastive = 0.5* centroid_contrastive_1+ 0.5*centroid_contrastive_2

                if confident_sample.shape[0]==0 and unconfident_sample.shape[0]!=0:
                    # confident_unlabeled_centroid,_ = obtain_cnn_centroid_feature(model,confident_sample)
                    unconfident_unlabeled_centroid,_ = obtain_cnn_centroid_feature(model,unconfident_sample)
        
                    unconfident_unlabeled_centroid = torch.tensor(unconfident_unlabeled_centroid)
                    sor_centroid = torch.tensor(sor_centroid)
                    centroid_features_2 = torch.cat([unconfident_unlabeled_centroid.unsqueeze(1),sor_centroid.unsqueeze(1)], dim=1)
                    centroid_contrastive_2= criterion_2(centroid_features_2,centroid_label)
                    # print('centroid_contrastive_1',centroid_contrastive_1.item())
                    # print('centroid_contrastive_2',centroid_contrastive_2.item())
                    centroid_contrastive = centroid_contrastive_2
                
                if confident_sample.shape[0]!=0 and unconfident_sample.shape[0]==0:
                    confident_unlabeled_centroid,_ = obtain_cnn_centroid_feature(model,confident_sample)
                    confident_unlabeled_centroid = torch.tensor(confident_unlabeled_centroid)
                    sor_centroid = torch.tensor(sor_centroid)
                    centroid_features_1 = torch.cat([confident_unlabeled_centroid.unsqueeze(1),sor_centroid.unsqueeze(1)], dim=1)
                    centroid_contrastive_1= criterion_2(centroid_features_1,centroid_label)
                    centroid_contrastive = centroid_contrastive_1

                if images_unconfident.shape[0]!=0 and images.shape[0]!=0:
                    loss = loss_ce + sup_condifent_loss_contrastive +  1.5*unconfident_unsup_loss_contrastive + 3*centroid_contrastive
                if images_unconfident.shape[0]==0 and images.shape[0]!=0:
                    loss = loss_ce + sup_condifent_loss_contrastive  + 3* centroid_contrastive
                    # print('loss_ce',loss_ce.item())
                    # print('condifent_loss_contrastive',sup_condifent_loss_contrastive.item())
                    # print('centroid_contrastive',centroid_contrastive.item())
                if images_unconfident.shape[0]!=0 and images.shape[0]==0:
                    loss = loss_ce + 1.5*unconfident_unsup_loss_contrastive  + 3 * centroid_contrastive
                    # print('loss_ce',loss_ce.item())
                    # print('unconfident_unsup_loss_contrastive',unconfident_unsup_loss_contrastive.item())
                    # print('centroid_contrastive',centroid_contrastive.item())

                
                if optim is not None:
                    optim.zero_grad()
                    loss.backward()
                    optim.step()
                    del loss
                    torch.cuda.empty_cache()
    # centroids,_ = gems_centroid(model, source_loader,labeled_loader,unlabeled_loader)
    # torch.save(centroids,'centroid_'+str(idx)+'.pt')
    model.cpu()
    # confident_unlabeled_centroid,_ = obtain_cnn_centroid_feature(model,confident_sample)
    torch.save(model.state_dict(),'local_'+str(idx)+'.pt')