{
 "cells": [
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "import os\n",
    "import sys\n",
    "import copy\n",
    "import math\n",
    "import numpy as np\n",
    "import torch\n",
    "import torch.nn as nn\n",
    "import torch.nn.functional as F\n",
    "\n",
    "\n",
    "def knn(x, k):\n",
    "    inner = -2*torch.matmul(x.transpose(2, 1), x)\n",
    "    xx = torch.sum(x**2, dim=1, keepdim=True)\n",
    "    pairwise_distance = -xx - inner - xx.transpose(2, 1)\n",
    " \n",
    "    idx = pairwise_distance.topk(k=k, dim=-1)[1]   # (batch_size, num_points, k)\n",
    "    return idx\n",
    "\n",
    "\n",
    "def get_graph_feature(x, k=20, idx=None):\n",
    "    batch_size = x.size(0)\n",
    "    num_points = x.size(2)\n",
    "    x = x.view(batch_size, -1, num_points)\n",
    "    if idx is None:\n",
    "        idx = knn(x, k=k)   # (batch_size, num_points, k)\n",
    "    device = torch.device('cuda')\n",
    "\n",
    "    idx_base = torch.arange(0, batch_size, device=device).view(-1, 1, 1)*num_points\n",
    "\n",
    "    idx = idx + idx_base\n",
    "\n",
    "    idx = idx.view(-1)\n",
    " \n",
    "    _, num_dims, _ = x.size()\n",
    "\n",
    "    x = x.transpose(2, 1).contiguous()   # (batch_size, num_points, num_dims)  -> (batch_size*num_points, num_dims) #   batch_size * num_points * k + range(0, batch_size*num_points)\n",
    "    feature = x.view(batch_size*num_points, -1)[idx, :]\n",
    "    feature = feature.view(batch_size, num_points, k, num_dims) \n",
    "    x = x.view(batch_size, num_points, 1, num_dims).repeat(1, 1, k, 1)\n",
    "    \n",
    "    feature = torch.cat((feature-x, x), dim=3).permute(0, 3, 1, 2)\n",
    "  \n",
    "    return feature\n",
    "\n",
    "\n",
    "class PointNet(nn.Module):\n",
    "    def __init__(self, args, output_channels=40):\n",
    "        super(PointNet, self).__init__()\n",
    "        self.args = args\n",
    "        self.conv1 = nn.Conv1d(3, 64, kernel_size=1, bias=False)\n",
    "        self.conv2 = nn.Conv1d(64, 64, kernel_size=1, bias=False)\n",
    "        self.conv3 = nn.Conv1d(64, 64, kernel_size=1, bias=False)\n",
    "        self.conv4 = nn.Conv1d(64, 128, kernel_size=1, bias=False)\n",
    "        self.conv5 = nn.Conv1d(128, args.emb_dims, kernel_size=1, bias=False)\n",
    "        self.bn1 = nn.BatchNorm1d(64)\n",
    "        self.bn2 = nn.BatchNorm1d(64)\n",
    "        self.bn3 = nn.BatchNorm1d(64)\n",
    "        self.bn4 = nn.BatchNorm1d(128)\n",
    "        self.bn5 = nn.BatchNorm1d(args.emb_dims)\n",
    "        self.linear1 = nn.Linear(args.emb_dims, 512, bias=False)\n",
    "        self.bn6 = nn.BatchNorm1d(512)\n",
    "        self.dp1 = nn.Dropout()\n",
    "        self.linear2 = nn.Linear(512, output_channels)\n",
    "\n",
    "    def forward(self, x):\n",
    "        x = F.relu(self.bn1(self.conv1(x)))\n",
    "        x = F.relu(self.bn2(self.conv2(x)))\n",
    "        x = F.relu(self.bn3(self.conv3(x)))\n",
    "        x = F.relu(self.bn4(self.conv4(x)))\n",
    "        x = F.relu(self.bn5(self.conv5(x)))\n",
    "        x = F.adaptive_max_pool1d(x, 1).squeeze()\n",
    "        x = F.relu(self.bn6(self.linear1(x)))\n",
    "        x = self.dp1(x)\n",
    "        x = self.linear2(x)\n",
    "        return x\n",
    "\n",
    "\n",
    "class DGCNN(nn.Module):\n",
    "    def __init__(self, args, output_channels=40):\n",
    "        super(DGCNN, self).__init__()\n",
    "        self.args = args\n",
    "        self.k = args.k\n",
    "        \n",
    "        self.bn1 = nn.BatchNorm2d(64)\n",
    "        self.bn2 = nn.BatchNorm2d(64)\n",
    "        self.bn3 = nn.BatchNorm2d(128)\n",
    "        self.bn4 = nn.BatchNorm2d(256)\n",
    "        self.bn5 = nn.BatchNorm1d(args.emb_dims)\n",
    "\n",
    "        self.conv1 = nn.Sequential(nn.Conv2d(6, 64, kernel_size=1, bias=False),\n",
    "                                   self.bn1,\n",
    "                                   nn.LeakyReLU(negative_slope=0.2))\n",
    "        self.conv2 = nn.Sequential(nn.Conv2d(64*2, 64, kernel_size=1, bias=False),\n",
    "                                   self.bn2,\n",
    "                                   nn.LeakyReLU(negative_slope=0.2))\n",
    "        self.conv3 = nn.Sequential(nn.Conv2d(64*2, 128, kernel_size=1, bias=False),\n",
    "                                   self.bn3,\n",
    "                                   nn.LeakyReLU(negative_slope=0.2))\n",
    "        self.conv4 = nn.Sequential(nn.Conv2d(128*2, 256, kernel_size=1, bias=False),\n",
    "                                   self.bn4,\n",
    "                                   nn.LeakyReLU(negative_slope=0.2))\n",
    "        self.conv5 = nn.Sequential(nn.Conv1d(512, args.emb_dims, kernel_size=1, bias=False),\n",
    "                                   self.bn5,\n",
    "                                   nn.LeakyReLU(negative_slope=0.2))\n",
    "        self.linear1 = nn.Linear(args.emb_dims*2, 512, bias=False)\n",
    "        self.bn6 = nn.BatchNorm1d(512)\n",
    "        self.dp1 = nn.Dropout(p=args.dropout)\n",
    "        self.linear2 = nn.Linear(512, 256)\n",
    "        self.bn7 = nn.BatchNorm1d(256)\n",
    "        self.dp2 = nn.Dropout(p=args.dropout)\n",
    "        self.linear3 = nn.Linear(256, output_channels)\n",
    "\n",
    "    def forward(self, x):\n",
    "        batch_size = x.size(0)\n",
    "        x = get_graph_feature(x, k=self.k)\n",
    "        x = self.conv1(x)\n",
    "        x1 = x.max(dim=-1, keepdim=False)[0]\n",
    "\n",
    "        x = get_graph_feature(x1, k=self.k)\n",
    "        x = self.conv2(x)\n",
    "        x2 = x.max(dim=-1, keepdim=False)[0]\n",
    "\n",
    "        x = get_graph_feature(x2, k=self.k)\n",
    "        x = self.conv3(x)\n",
    "        x3 = x.max(dim=-1, keepdim=False)[0]\n",
    "\n",
    "        x = get_graph_feature(x3, k=self.k)\n",
    "        x = self.conv4(x)\n",
    "        x4 = x.max(dim=-1, keepdim=False)[0]\n",
    "\n",
    "        x = torch.cat((x1, x2, x3, x4), dim=1)\n",
    "\n",
    "        x = self.conv5(x)\n",
    "        x1 = F.adaptive_max_pool1d(x, 1).view(batch_size, -1)\n",
    "        x2 = F.adaptive_avg_pool1d(x, 1).view(batch_size, -1)\n",
    "        x = torch.cat((x1, x2), 1)\n",
    "\n",
    "        x = F.leaky_relu(self.bn6(self.linear1(x)), negative_slope=0.2)\n",
    "        x = self.dp1(x)\n",
    "        x = F.leaky_relu(self.bn7(self.linear2(x)), negative_slope=0.2)\n",
    "        x = self.dp2(x)\n",
    "        x = self.linear3(x)\n",
    "        return x"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.7.3"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 2
}
