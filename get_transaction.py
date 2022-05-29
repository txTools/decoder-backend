import traceback
import sys
from functools import lru_cache
from web3 import Web3
# from web3.auto import w3
from web3.contract import Contract
from web3._utils.events import get_event_data
from web3._utils.abi import exclude_indexed_event_inputs, get_abi_input_names, get_indexed_event_inputs, normalize_event_input_types
from web3.exceptions import MismatchedABI, LogTopicError
from web3.types import ABIEvent
from eth_utils import event_abi_to_log_topic, to_hex
from hexbytes import HexBytes
from flask import Flask, request, jsonify

app = Flask(__name__)

import json
import re
import requests


"""
Uniswap: 0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D
Sushiswap: 0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F
usdt: 0xdAC17F958D2ee523a2206206994597C13D831ec7
ethereum: 0x
"""

tokenMapping = {
  "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45" : "Uniswap",
  "0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F" : "Sushiswap",
  "0xBC4CA0EdA7647A8aB7C2061c2E118A18a936f13D" : "BAYC"
}

w3 = Web3(Web3.HTTPProvider('https://mainnet.infura.io/v3/8220e40371b34960922e067f3dc6948a'))

def decode_tuple(t, target_field):
    output = dict()
    for i in range(len(t)):
        if isinstance(t[i], (bytes, bytearray)):
            output[target_field[i]['name']] = to_hex(t[i])
        elif isinstance(t[i], (tuple)):
            output[target_field[i]['name']] = decode_tuple(
            t[i], target_field[i]['components'])
        else:
            output[target_field[i]['name']] = t[i]
    return output


def decode_list_tuple(l, target_field):
  output = l
  for i in range(len(l)):
    output[i] = decode_tuple(l[i], target_field)
  return output

def decode_list(l):
  output = l
  for i in range(len(l)):
    if isinstance(l[i], (bytes, bytearray)):
      output[i] = to_hex(l[i])
    else:
      output[i] = l[i]
  return output


def convert_to_hex(arg, target_schema):
    """
    utility function to convert byte codes into human readable and json serializable data structures
    """
    output = dict()
    for k in arg:
        if isinstance(arg[k], (bytes, bytearray)):
            output[k] = to_hex(arg[k])
        elif isinstance(arg[k], (list)) and len(arg[k]) > 0:
            target = [a for a in target_schema if 'name' in a and a['name'] == k][0]
            if target['type'] == 'tuple[]':
                target_field = target['components']
                output[k] = decode_list_tuple(arg[k], target_field)
            else:
                output[k] = decode_list(arg[k])
        elif isinstance(arg[k], (tuple)):
            target_field = [a['components'] for a in target_schema if 'name' in a and a['name'] == k][0]
            output[k] = decode_tuple(arg[k], target_field)
    else:
      output[k] = arg[k]
    return output

@lru_cache(maxsize=None)
def _get_contract(address, abi):
  """
  This helps speed up execution of decoding across a large dataset by caching the contract object
  It assumes that we are decoding a small set, on the order of thousands, of target smart contracts
  """
  if isinstance(abi, (str)):
    abi = json.loads(abi)

  contract = w3.eth.contract(address=Web3.toChecksumAddress(address), abi=abi)
  return (contract, abi)

def decode_tx(address, input_data, abi):
  if abi is not None:
    try:
      (contract, abi) = _get_contract(address, abi)
      func_obj, func_params = contract.decode_function_input(input_data)
      target_schema = [a['inputs'] for a in abi if 'name' in a and a['name'] == func_obj.fn_name][0]
      decoded_func_params = convert_to_hex(func_params, target_schema)
      return (func_obj.fn_name, json.dumps(decoded_func_params), json.dumps(target_schema))
    except:
      e = sys.exc_info()[0]
      return ('decode error', repr(e), None)
  else:
    return ('no matching abi', None, None)

# sample_abi = 

ETHERSCAN_API_KEY = "SA2W4B5HJP11B4WTX6679QS5PCU6RM9QFY"

def getTokenInfo(address):
    abi_endpoint = f"https://api.etherscan.io/api?module=contract&action=getabi&address={address}&apikey={ETHERSCAN_API_KEY}"
    abi = json.loads(requests.get(abi_endpoint).text)

    abi_token = json.loads(abi['result'])


    tokenContract = w3.eth.contract(address = address, abi = abi_token)
    tokenName = tokenContract.functions.name().call()
    tokenDec = tokenContract.functions.decimals().call()

    return tokenName, tokenDec

tx_hash = "0x245015ce504d7e532ff1d03e931622886a150a4342a23d9288644afa546f0fa4"

@app.route('/<string:tx_hash>/')
def get_transaction(tx_hash):

    tx = w3.eth.get_transaction(tx_hash)

    # print(tx)

    if(tx['input'] == '0x'):
      sender = tx['from']
      to = tx['to']
      val = tx['value'] / 10**18

      return("{} sent {} {} ETH".format(sender, to, val))

    else:

        abi_endpoint = f"https://api.etherscan.io/api?module=contract&action=getabi&address={tx['to']}&apikey={ETHERSCAN_API_KEY}"
        abi = json.loads(requests.get(abi_endpoint).text)

        contract = w3.eth.contract(address=tx["to"], abi=abi["result"])
        output = decode_tx(tx['to'], tx['input'], abi['result'])

        # if('swap' in output[0] or 'multicall' in output[0]):

        print(output[0])

        if(output[0] == 'swapTokensForExactTokens'):
          func_obj, func_params = contract.decode_function_input(tx['input'])

          amountOut = func_params["amountOut"]
          amountIn = func_params['amountInMax']
          token = func_params['path'][-1]

          tokenAbiEndpoint = f"https://api.etherscan.io/api?module=contract&action=getabi&address={token}&apikey={ETHERSCAN_API_KEY}"
          tokenAbi = json.loads(requests.get(tokenAbiEndpoint).text)

          abi_token = json.loads(tokenAbi['result'])


          tokenContract = w3.eth.contract(address = token, abi = abi_token)
          tokenName = tokenContract.functions.name().call()
          tokenDec = tokenContract.functions.decimals().call()

          return("{} swapped {} ETH for {} {} on {}".format(tx['from'], amountIn / 10**18, amountOut / 10**tokenDec, tokenName, tokenMapping[tx['to']]) )

        elif(output[0] == 'multicall'):

          output = decode_tx(tx['to'], json.loads(output[1])['data'][0], abi['result'])
          output = json.loads(output[1])
          print(output)
          fromToken, fromDec = getTokenInfo(output['params'][0])
          toToken, toDec = getTokenInfo(output['params'][1])
          amountIn = output['params'][4]
          amountOut = output['params'][5]

          return("{} swapped {} {} for {} {} on {}".format(tx['from'], amountIn / 10**fromDec, fromToken, amountOut / 10**toDec, toToken, tokenMapping[tx['to']]) )

        elif(output[0] == 'transfer'):
          # output = decode_tx(tx['to'], tx['input'], abi['result'])

          contract = w3.eth.contract(address=tx["to"], abi=abi["result"])
          func_obj, func_params = contract.decode_function_input(tx['input'])

          amt = func_params['_value']
          tokenName, tokenDec = getTokenInfo(tx['to'])
          to = func_params['_to']

          return("{} sent {} {} to {}".format(tx['from'], amt / 10**tokenDec, tokenName, to))


          # print('function called: ', output[0])
          # print('arguments: ', json.dumps(json.loads(output[1]), indent=2))

          # print(output[1])
          # print(tx['from'])
          # print(tx['to'])

        elif(output[0] == 'transferFrom'):
          contract = w3.eth.contract(address=tx["to"], abi=abi["result"])
          func_obj, func_params = contract.decode_function_input(tx['input'])
          # print(tx['to'])
          # print(func_params)

          return("{} sent {} #{} to {}".format(tx['from'], tokenMapping[tx['to']], func_params['tokenId'], func_params['to']) )




          # val = json.loads(output)['value']


        # transaction = json.loads(output[1])

        # print(tx)





        return "{from} called swap on {to} and sent"

# get_transaction(tx_hash)

if(__name__ == '__main__'):
    app.run()

# buyData = json.loads(output[1])["calldataBuy"]
# sellData = json.loads(output[1])["calldataSell"]
# print("#########")
# print(decode_tx(tx['to'], buyData, abi['result']))


