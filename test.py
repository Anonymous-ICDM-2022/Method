import torch
import numpy as np
import torch.nn as nn
from model import RiskPre, NeuralHmm
from sklearn.utils import class_weight
from utils import print_metrics_binary, neuralhmm_loss, setup_seed, data_extract
from data_process import data_process_x, data_process_s


def test_riskpre(test_loader,
                  idx_list,
                  demographic_data,
                  diagnosis_data,
                  file_name,
                  input_dim,
                  h_dim,
                  s_dim,
                  gru_dim,
                  gru_num_layers,
                  gru_dropout_rate,
                  hidden_dim_,
                  seq_len,
                  out_dim,
                  n_gaussian,
                  seed,
                  device,
                  model_name = 'RiskPre'):

    setup_seed(seed)
    model = RiskPre(input_dim, h_dim, s_dim, gru_dim, gru_num_layers, gru_dropout_rate, hidden_dim_, seq_len, out_dim, n_gaussian, device).to(device)
    checkpoint = torch.load(file_name)
    model.load_state_dict(checkpoint['net'])
    model.eval()

    h_gru_test = []
    mu_q_test = []
    var_q_test = []
    batch_x_test = []
    batch_y_test = []
    batch_name_test = []
    test_out = []
    test_loss = []
    batch_loss = []
    y_true = []
    y_pred = []

    for step, (batch_x, batch_y, batch_name) in enumerate(test_loader):
        batch_x = batch_x.float().to(device)
        batch_y = batch_y.float().to(device)
        batch_name_test.append(batch_name)
        batch_x_test.append(batch_x.cpu().detach().numpy())
        batch_y_test.append(batch_y.cpu().detach().numpy())

        batch_demo = []
        batch_diag = []
        for i in range(len(batch_name)):
            cur_id, cur_ep, _ = batch_name[i].split('_', 2)
            cur_idx = cur_id + '_' + cur_ep
            idx = idx_list.index(cur_idx) if cur_idx in idx_list else None
            if idx == None:
                cur_demo = torch.zeros(4)
                cur_diag = torch.zeros(128)
            else:
                cur_demo = torch.tensor(demographic_data[idx], dtype=torch.float32)
                cur_diag = torch.tensor(diagnosis_data[idx], dtype=torch.float32)
            batch_demo.append(cur_demo)
            batch_diag.append(cur_diag)

        batch_demo = torch.stack(batch_demo).to(device)
        batch_diag = torch.stack(batch_diag).to(device)
        batch_s = torch.cat((batch_demo, batch_diag), 1)
        sample_c, h_gru, mu_q, var_q = model(batch_x, batch_s)
        h_gru_test.append(h_gru.cpu().detach().numpy())
        mu_q_test.append(mu_q.cpu().detach().numpy())
        var_q_test.append(var_q.cpu().detach().numpy())

        batch_y = batch_y.long()
        y_out = batch_y.cpu().numpy()
        class_weights = class_weight.compute_class_weight(class_weight='balanced', classes=np.unique(y_out),
                                                          y=y_out)
        class_weights = torch.tensor(class_weights, dtype=torch.float).to(device)
        criterion = nn.CrossEntropyLoss(weight=class_weights, reduction='mean')

        loss = criterion(sample_c, batch_y)
        batch_loss.append(loss.cpu().detach().numpy())

        y_pred.append(sample_c)
        y_true.append(batch_y)

    test_loss.append(np.mean(np.array(batch_loss)))
    print('\n==>Predicting on test')
    print('Test Loss = %.4f' % (test_loss[-1]))
    print()
    y_pred = torch.cat(y_pred, 0)
    y_true = torch.cat(y_true, 0)
    test_y_pred = y_pred.cpu().detach().numpy()
    test_y_true = y_true.cpu().detach().numpy()
    ret = print_metrics_binary(test_y_true, test_y_pred)

    cur_auroc = ret['auroc']
    cur_auprc = ret['auprc']
    test_out.extend([[h_gru_test, mu_q_test, var_q_test, batch_x_test, batch_y_test, batch_name_test]])

    return cur_auroc, cur_auprc, test_out


def test_neuralhmm(idx_list,
                 demographic_data,
                 diagnosis_data,
                 h_gru_test,
                 mu_q_test,
                 var_q_test,
                 batch_x_test,
                 batch_name_test,
                 file_name,
                 h_dim,
                 s_dim,
                 emission_dim,
                 out_dim,
                 transition_dim_,
                 transition_dim,
                 seed,
                 device,
                 model_name = 'NeuralHmm'):

    setup_seed(seed)
    model = NeuralHmm(h_dim, s_dim, emission_dim, out_dim, transition_dim_, transition_dim, device).to(device)
    checkpoint = torch.load(file_name)
    model.load_state_dict(checkpoint['net'])
    model.eval()
    batch_loss = []

    for step in range(len(batch_x_test)):
        batch_x = torch.tensor(batch_x_test[step]).to(device)
        batch_name = batch_name_test[step]

        batch_demo = []
        batch_diag = []
        for i in range(len(batch_name)):
            cur_id, cur_ep, _ = batch_name[i].split('_', 2)
            cur_idx = cur_id + '_' + cur_ep
            idx = idx_list.index(cur_idx) if cur_idx in idx_list else None
            if idx == None:
                cur_demo = torch.zeros(4)
                cur_diag = torch.zeros(128)
            else:
                cur_demo = torch.tensor(demographic_data[idx], dtype=torch.float32)
                cur_diag = torch.tensor(diagnosis_data[idx], dtype=torch.float32)
            batch_demo.append(cur_demo)
            batch_diag.append(cur_diag)

        batch_demo = torch.stack(batch_demo).to(device)
        batch_diag = torch.stack(batch_diag).to(device)
        batch_s = torch.cat((batch_demo, batch_diag), 1)
        h_gru = torch.tensor(h_gru_test[step]).to(device)
        mu_q_seq = torch.tensor(mu_q_test[step]).to(device)
        var_q_seq = torch.tensor(var_q_test[step]).to(device)

        x_recon, x, mu_p_seq, var_p_seq = model(batch_x, batch_s, h_gru)

        kl_raw, nll_raw, kl_fr, nll_fr, kl_m, nll_m, loss = \
            neuralhmm_loss(x, x_recon, mu_q_seq, var_q_seq, mu_p_seq, var_p_seq)
        batch_loss.append(loss.cpu().detach().numpy())

    test_loss_ = np.mean(np.array(batch_loss))
    print('\n==>Predicting on test')
    print('Test Loss = %.4f' % test_loss_)
    print()

    return test_loss_

if __name__ == '__main__':
    # parameters
    data_x_path = './data_x/'
    data_s_path = './data_s/'
    file_name_riskpre = './model/riskpre'
    input_dim = 76
    h_dim = 12
    s_dim = 132
    gru_dim = 36
    gru_num_layers = 1
    gru_dropout_rate = 0
    hidden_dim_ = 16
    seq_len = 60
    out_dim = 17
    n_gaussian = 8
    seed = 2022
    device = 'cuda:0'

    _, _, test_loader = data_process_x(data_x_path)
    demographic_data, diagnosis_data, idx_list = data_process_s(data_s_path)

    cur_auroc, cur_auprc, test_out = test_riskpre(test_loader, idx_list, demographic_data, diagnosis_data, \
                                                  file_name_riskpre, input_dim, h_dim, s_dim, gru_dim, gru_num_layers, \
                                                  gru_dropout_rate, hidden_dim_, seq_len, out_dim, n_gaussian, seed, device, model_name = 'RiskPre')
    print('-------------best performance----------')
    print('Test Auroc = %.4f ' % (cur_auroc))
    print('Test Auprc = %.4f ' % (cur_auprc))
    print()

    # parameters
    file_name_neuralhmm = './model/neuralhmm'
    emission_dim = 32
    x_dim = 76
    transition_dim_ = 32
    transition_dim = 24
    seed = 2022
    device = 'cuda:0'

    h_gru_test, mu_q_test, var_q_test, batch_x_test, batch_y_test, batch_name_test = data_extract(test_out, None)
    test_loss_ = test_neuralhmm(idx_list, demographic_data, diagnosis_data, h_gru_test, mu_q_test, var_q_test, \
                              batch_x_test, batch_name_test, file_name_neuralhmm, h_dim, s_dim, emission_dim, x_dim, \
                              transition_dim_, transition_dim, seed, device, model_name = 'NeuralHmm')
    print('-------------best performance----------')
    print('Neural Hmm Test Loss = %.4f ' % (test_loss_))
