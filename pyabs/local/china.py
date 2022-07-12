from dataclasses import dataclass
from datetime import datetime
import functools
import requests
import pandas as pd
from enum import Enum

from pyabs import *
import json

class 频率(Enum):
   每月 = 12
   每季度  = 4
   每半年 = 2
   每年 = 1

freqMap = {"每月":"Monthly"
           ,"每年":"Annually"
           ,"每季度":"Quarterly"
           ,"每半年":"SemiAnnually"}

def mkBondType(x):
    match x:
        case {"固定摊还":schedule}:
            return {
               "tag":"PAC",
               "contents":{
                  "tag":"AmountCurve",
                  "contents":schedule}}
        case {"过手摊还":None}:
            return {"tag":"Sequential"}
        case {"锁定摊还":_after}:
            return {"tag":"Lockout"
                     ,"contents":_after}        
        case {"期间收益":_yield}:
            return {"tag":"InterestByYield"
                     ,"contents":_yield} 
        case _ :
            return {}        
        

def mkAccType(x):
    baseMap = {"资产池余额":"CurrentPoolBalance"}
    match x :
        case {"固定储备金额":amt}:
            return {"tag":"FixReserve","contents":amt}
        case {"目标储备金额":[base,rate]}:
            return {"tag":"PctReserve"
                    ,"contents":[{"tag":baseMap[base]},rate]}        
        case _ :
            return {}

def mkFeeType(x):
    baseMap = {"资产池余额":"CurrentPoolBalance"
              ,"资产池当期利息":"PoolCollectionInt"}    
    match x :
        case {"年化费率":[base,rate]}:
            return {"tag":"AnnualRateFee"
                    ,"contents":[{"tag":baseMap[base]},rate]}  
        case {"百分比费率":[base,rate]}:
            return {"tag":"PctFee"
                    ,"contents":[{"tag":baseMap[base]},rate]}  
        case _ :
            return {}

def mkBondRate(x):
    indexMapping = {"LPR5Y":"LPR5Y","LIBOR1M":"LIBOR1M"}
    match x:
        case {"浮动":[_index,Spread,resetInterval]}:
            return {"tag":"Floater"
                    ,"contents":[indexMapping[_index]
                                ,Spread
                                ,freqMap[resetInterval]
                                ,None
                                ,None]}
        case {"固定":[_rate]}:
            return {"tag":"Fix"
                    ,"contents":_rate}
        
        case {"期间收益":_yield}:
            return {"tag":"InterestByYield"
                     ,"contents":_yield}         
        case _ :
            return {}

def mkFeeCapType(x):
    match x:
        case {"应计费用百分比":pct}:
            return {
              "tag": "DuePct",
              "contents": pct
            }
        case {"应计费用上限":amt}:
            return {
              "tag": "DueCapAmt",
              "contents": amt}            
        
def mkWaterfall(x):
    match x :
        case ["账户转移",source,target]:
            return {"tag":"Transfer"
                   ,"contents":[source,target,""]}
        case ["公式转移",source,target,formula]:
            return {"tag":"TransferBy"
                   ,"contents":[source,target,formula]}
        case ["支付费用",source,target]:
            return {"tag":"PayFee"
                   ,"contents":[source,target]}
        case ["支付费用限额",source,target,_limit]:
            limit = mkFeeCapType(_limit)
            return {"tag":"PayFeeBy"
                   ,"contents":[limit,source,target]}
        case ["支付利息",source,target]:
            return {"tag":"PayInt"
                   ,"contents":[source,target]}
        case ["支付本金",source,target]:
            return {"tag":"PayPrin"
                   ,"contents":[source,target]}
        case ["支付期间收益",source,target]:
            return {"tag":"PayTillYield"
                   ,"contents":[source,target]}     
        case ["支付收益",source,target]:
            return {"tag":"PayResidual"
                   ,"contents":[source,target]}           
        case ["储备账户转移",source,target]:
            return {"tag":"TransferReserve"
                   ,"contents":[keep,source,target]}     
        case _ :
            return {}


def mkAsset(x):
    _typeMapping = {"等额本息":"Level","等额本金":"Even"}
    match x :
        case ["按揭贷款"
              ,{"放款金额":originBalance,"放款利率":originRate,"初始期限":originTerm
               ,"频率":freq,"类型":_type}
              ,{"当前余额":currentBalance
                ,"当前利率":currentRate
                ,"剩余期限":remainTerms}
             ]:
            return [{"originBalance":originBalance,
                  "originRate":{
                     "tag":"Fix",
                     "contents":originRate
                  },
                  "originTerm":originTerm,
                  "period":freqMap[freq],
                  "startDate":"2019-01-05",
                  "prinType":_typeMapping[_type]},
                  currentBalance,
                  currentRate,
                  remainTerms]
                
        case _ :
            return {}
        
def mkCollection(xs):
    sourceMapping = {"利息回款":"CollectedInterest","本金回款":"CollectedPrincipal"
                     ,"早偿回款":"CollectedPrepayment","回收回款":"CollectedRecoveries"}
    return [[sourceMapping[x],acc] for (x,acc) in xs ]

def mkCall(x):
    match x :
        case _ :
            return {}

def mkDate(x):
    match x :
        case {"起息日":d}:
            return {"closing-date":d}
        case {"首次兑付日":d}:
            return {"first-pay-date":d}        
        case {"封包日":d}:
            return {"cutoff-date":d}

def mkComponent(x):
    match x:
        case {"贴现日":pricingDay,"贴现曲线":xs}:
           return [pricingDay,{"tag":"FloatCurve","contents":xs}]
        case _ : None

def mk(x):
    match x:
        case  ["资产",assets]:
            return {"assets": [ mkAsset(a) for a in assets]}
        case  ["账户",accName,{"余额":bal,"类型":accType}]:
            return {accName:{"accBalance":bal,"accName":accName,"accType":mkAccType(accType),"accInterest":None,"accStmt":None}}
        case  ["账户",accName,{"余额":bal}]:
            return {accName:{"accBalance":bal,"accName":accName,"accType":None,"accInterest":None,"accStmt":None}}
        case  ["费用",feeName,{"类型":feeType}]:
            return {feeName:{"feeName":feeName,"feeType":mkFeeType(feeType),"feeStart":None,"feeDue":0,"feeArrears":0,"feeLastPaidDay":None}}
        case  ["债券",bndName,{"当前余额":bndBalance
                             ,"当前利率":bndRate
                            ,"初始余额":originBalance
                             ,"初始利率":originRate
                             ,"起息日":originDate
                             ,"利率":bndInterestInfo
                             ,"债券类型":bndType
                            }]:
            return {bndName:
                    {"bndName":bndName
                     ,"bndBalance":bndBalance
                    ,"bndRate":bndRate
                    ,"bndOriginInfo":
                     {"originBalance":originBalance
                     ,"originDate":originDate
                     ,"originRate":originRate}
                    ,"bndInterestInfo":mkBondRate(bndInterestInfo)
                    ,"bndType":mkBondType(bndType)
                    ,"bndDuePrin":0
                    ,"bndDueInt":0
                    }}
        case  ["分配规则",instruction]:
            return mkWaterfall(instruction)
        case  ["归集规则",collection]:
            return mkCollection(instruction)
        case  ["清仓回购",calls]:
            return mkCall(calls)
        case _ :
            print("Failed to match x")
            return {}

@dataclass
class 信贷ABS:
    名称: str
    日期:tuple # 起息日: datetime 封包日: datetime 首次兑付日 : datetime
    兑付频率 : 频率
    资产池: tuple
    账户: tuple
    债券: tuple 
    费用: tuple
    分配规则: tuple
    归集规则: tuple
    清仓回购: tuple

    @property
    def __dict__(self):
        """
        get a python dictionary
        """
        return asdict(self)

    @property
    def json(self):
        closing,cutoff,first_pay = self.日期
        """
        get the json formatted string
        """
        _r = {
            "dates":{
                "closing-date": closing,
                "cutoff-date": cutoff,
                "first-pay-date": first_pay},
            "name":self.名称,
            "pool":{"assets":[mkAsset(x) for x in self.资产池]
                    ,"asOfDate":cutoff},
            "bonds": functools.reduce(lambda result,current:result|current
                            ,[mk(['债券',bn,bo]) for (bn,bo) in self.债券]),
            "waterfall": {"base":[ mkWaterfall(w) for w in self.分配规则['违约前']]},
            "fees": functools.reduce(lambda result,current:result|current
                    ,[mk(["费用",feeName, feeO]) for (feeName,feeO) in  self.费用]),
            "accounts": functools.reduce(lambda result,current:result|current
                    , [mk(["账户",accName, accO]) for (accName,accO) in self.账户]),
            "collects": mkCollection(self.归集规则),
            "collectPeriod": freqMap[self.兑付频率],
            "payPeriod": freqMap[self.兑付频率],
        }
        for fn,fo in _r['fees'].items():
             fo['feeStart'] = _r['dates']['closing-date']
        return _r #,ensure_ascii=False)

    def debug_run(self,assump):
        return json.dumps({"deal":self.json,"assump":assump}
                          ,ensure_ascii=False)


    def run(self, assump, pricingInput=None, read=True):
        default_URL = "http://localhost:8081/run_deal2"
        hdrs = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        req = json.dumps({"deal":self.json
                             ,"assump":assump
                             ,"bondPricing":mkComponent(pricingInput)}
                         ,ensure_ascii=False)
        #print(req)
        r = requests.post(default_URL
                          ,data=req.encode('utf-8')
                          ,headers=hdrs)
        self.result = json.loads(r.text)
        #if read:
        #    return r
        #self.result = r

    def read(self):
        read_paths = {'bonds':
                        ('bndStmt',["日期","余额","利息","本金","执行利率","本息合计","备注"],"债券")
                      ,'fees':
                        ('feeStmt',["日期","余额","支付","剩余支付","备注"],"费用")
                      ,'accounts':
                        ('accStmt',["日期","余额","变动额","备注"],"账户")
                      }
        output = {}
        for comp_name,comp_v in read_paths.items():
            output[comp_name] = {}
            for k,x in self.result[0][comp_name].items():
                ir = None
                if x[comp_v[0]]:
                    ir = [_['contents'] for _ in x[comp_v[0]]]
                output[comp_name][k] = pd.DataFrame(ir,columns=[comp_v[1]])
        output['pool'] = {}
        output['pool']['flow'] = pd.DataFrame([ _['contents'] for _ in self.result[0]['pool']['futureCf'] ]
                                              ,columns=["日期","未偿余额","本金","利息","早偿金额","违约金额","回收金额"])

        output['pricing'] = self.result[3]
        return output